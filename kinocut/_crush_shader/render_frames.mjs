#!/usr/bin/env node
/**
 * Headless CRUSH shader renderer — processes video frames via WebGL.
 *
 * Usage: node render_frames.mjs '<JSON config>'
 *
 * Config shape:
 * {
 *   "effect": "digital_feedback",
 *   "inputDir": "/tmp/.../frames",
 *   "outputDir": "/tmp/.../rendered",
 *   "frameCount": 120,
 *   "params": { "u_feedback_mix": 0.5, ... }
 * }
 */

import { createCanvas, loadImage } from 'canvas';
import { readFileSync, writeFileSync } from 'fs';
import { join, resolve } from 'path';
import { exit } from 'process';

const ALLOWED_EFFECTS = new Set([
    'digital_feedback', 'slit_scan', 'depth_splatting', 'point_cloud',
]);

const MAX_FRAMES = 7200;
const PAST_BUFFER_COUNT = 8;

async function main() {
    const config = JSON.parse(process.argv[2]);
    const { effect, inputDir, outputDir, frameCount, params } = config;

    const CRUSH_JS_SRC = config.crushPath
        ? resolve(config.crushPath)
        : (process.env.MCP_VIDEO_CRUSH_PATH
            ? resolve(process.env.MCP_VIDEO_CRUSH_PATH)
            : resolve(import.meta.dirname, '../../../../CRUSH_SHADERS/crush-js/src'));

    // Validate effect name against allowlist
    if (!ALLOWED_EFFECTS.has(effect)) {
        console.error(`Invalid effect: ${effect}. Allowed: ${[...ALLOWED_EFFECTS].join(', ')}`);
        exit(1);
    }

    // Cap frame count
    if (frameCount > MAX_FRAMES) {
        console.error(`Frame count ${frameCount} exceeds maximum ${MAX_FRAMES}`);
        exit(1);
    }

    // Read effect GLSL sources
    const commonGLSL = readFileSync(join(CRUSH_JS_SRC, 'common.glsl'), 'utf-8');
    const effectGLSL = readFileSync(join(CRUSH_JS_SRC, 'effects', `${effect}.glsl`), 'utf-8');

    // Create headless canvas at first frame's dimensions
    const firstFrame = await loadImage(join(inputDir, 'frame_000001.png'));
    const width = firstFrame.width;
    const height = firstFrame.height;

    const canvas = createCanvas(width, height);
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');

    if (!gl) {
        console.error('ERROR: WebGL not available in headless canvas');
        exit(1);
    }

    // Compile shaders
    const vertSrc = `
        attribute vec2 a_position;
        varying vec2 v_uv;
        void main() {
            v_uv = a_position * 0.5 + 0.5;
            gl_Position = vec4(a_position, 0.0, 1.0);
        }
    `;

    // Build fragment source: prepend common utilities (strip include guard)
    const commonBody = commonGLSL
        .replace('#ifndef CRUSH_COMMON_GLSL', '')
        .replace('#define CRUSH_COMMON_GLSL', '')
        .replace('#endif', '');
    const fragSrc = `precision highp float;
precision highp sampler2D;
${commonBody}
${effectGLSL.replace(/uniform sampler2D u_texture;/, 'uniform sampler2D u_texture;\nvarying vec2 v_uv;')
             .replace(/gl_FragCoord\.xy \/ u_resolution/g, 'v_uv')}
`;

    const vertShader = compileShader(gl, gl.VERTEX_SHADER, vertSrc);
    const fragShader = compileShader(gl, gl.FRAGMENT_SHADER, fragSrc);
    const program = linkProgram(gl, vertShader, fragShader);

    // Setup quad
    const quadBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
        -1, -1,  1, -1,  -1, 1,
        -1,  1,  1, -1,   1, 1,
    ]), gl.STATIC_DRAW);

    const posLoc = gl.getAttribLocation(program, 'a_position');
    gl.enableVertexAttribArray(posLoc);
    gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

    // Create input texture
    const inputTex = createAndSetupTexture(gl, gl.TEXTURE0);

    // Previous frame texture for digital_feedback
    const prevTex = createAndSetupTexture(gl, gl.TEXTURE1);

    // Multi-frame history textures for slit_scan
    const pastTextures = [];
    for (let i = 0; i < PAST_BUFFER_COUNT; i++) {
        pastTextures.push(createAndSetupTexture(gl, gl.TEXTURE2 + i));
    }

    gl.useProgram(program);

    // Introspect uniform types for correct dispatch
    const uniformTypes = getUniformTypes(gl, program);

    // Circular buffer for past frames (slit_scan)
    const pastFrameBuffers = [];
    for (let i = 0; i < PAST_BUFFER_COUNT; i++) {
        pastFrameBuffers.push(null);
    }
    let pastWriteIdx = 0;

    // Process frames
    for (let i = 0; i < frameCount; i++) {
        const frameNum = String(i + 1).padStart(6, '0');
        const framePath = join(inputDir, `frame_${frameNum}.png`);

        try {
            const img = await loadImage(framePath);
            const frameCanvas = createCanvas(width, height);
            const ctx = frameCanvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            const imgData = ctx.getImageData(0, 0, width, height);

            // Upload frame to texture
            gl.activeTexture(gl.TEXTURE0);
            gl.bindTexture(gl.TEXTURE_2D, inputTex);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, imgData.data);

            // Set sampler uniforms
            setUniform(gl, program, uniformTypes, 'u_texture', 0);
            setUniform(gl, program, uniformTypes, 'u_prev_frame', 1);
            for (let j = 0; j < PAST_BUFFER_COUNT; j++) {
                setUniform(gl, program, uniformTypes, `u_past_${j}`, 2 + j);
            }
            setUniform(gl, program, uniformTypes, 'u_resolution', [width, height]);
            setUniform(gl, program, uniformTypes, 'u_time', i / 30.0);
            setUniform(gl, program, uniformTypes, 'u_frame', i);

            // Apply effect params with type-correct dispatch
            for (const [key, val] of Object.entries(params)) {
                setUniform(gl, program, uniformTypes, key, val);
            }

            // Render
            gl.viewport(0, 0, width, height);
            gl.drawArrays(gl.TRIANGLES, 0, 6);

            // Read pixels
            const pixels = new Uint8Array(width * height * 4);
            gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);

            // Copy to previous frame texture (digital_feedback)
            gl.activeTexture(gl.TEXTURE1);
            gl.bindTexture(gl.TEXTURE_2D, prevTex);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, pixels);

            // Rotate into past frame buffer (slit_scan)
            pastFrameBuffers[pastWriteIdx] = new Uint8Array(pixels);
            pastWriteIdx = (pastWriteIdx + 1) % PAST_BUFFER_COUNT;

            // Upload past frame textures for slit_scan
            for (let j = 0; j < PAST_BUFFER_COUNT; j++) {
                // Most recent first: past_0 = frame just before current
                const bufIdx = (pastWriteIdx - 1 - j + PAST_BUFFER_COUNT * 2) % PAST_BUFFER_COUNT;
                const pastData = pastFrameBuffers[bufIdx];
                if (pastData) {
                    gl.activeTexture(gl.TEXTURE2 + j);
                    gl.bindTexture(gl.TEXTURE_2D, pastTextures[j]);
                    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, pastData);
                }
            }

            // Write output PNG
            const outCanvas = createCanvas(width, height);
            const outCtx = outCanvas.getContext('2d');
            const outData = outCtx.createImageData(width, height);
            outData.data.set(pixels);
            outCtx.putImageData(outData, 0, 0);

            const outBuf = outCanvas.toBuffer('image/png');
            writeFileSync(join(outputDir, `frame_${frameNum}.png`), outBuf);

            if ((i + 1) % 30 === 0) {
                console.log(`Processed ${i + 1}/${frameCount} frames`);
            }
        } catch (err) {
            console.error(`Error processing frame ${frameNum}: ${err.message}`);
        }
    }

    console.log(`Done: ${frameCount} frames rendered`);
}

function createAndSetupTexture(gl, unit) {
    gl.activeTexture(unit);
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    return tex;
}

function getUniformTypes(gl, program) {
    const types = {};
    const count = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) {
        const info = gl.getActiveUniform(program, i);
        if (info) types[info.name] = info.type;
    }
    return types;
}

function setUniform(gl, program, uniformTypes, name, value) {
    const loc = gl.getUniformLocation(program, name);
    if (loc === null) return;

    const type = uniformTypes[name];

    if (Array.isArray(value)) {
        if (value.length === 2) gl.uniform2f(loc, value[0], value[1]);
        else if (value.length === 3) gl.uniform3f(loc, value[0], value[1], value[2]);
        else if (value.length === 4) gl.uniform4f(loc, value[0], value[1], value[2], value[3]);
        return;
    }

    // Dispatch by GL type: SAMPLER and INT use uniform1i, FLOAT uses uniform1f
    const glInt = (type === gl.SAMPLER_2D || type === gl.INT
                   || type === gl.SAMPLER_CUBE || type === gl.UNSIGNED_INT);
    if (glInt) {
        gl.uniform1i(loc, Math.round(value));
    } else {
        gl.uniform1f(loc, value);
    }
}

function compileShader(gl, type, src) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, src);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        const info = gl.getShaderInfoLog(shader);
        gl.deleteShader(shader);
        console.error(`Shader compile error: ${info}`);
        exit(1);
    }
    return shader;
}

function linkProgram(gl, vert, frag) {
    const prog = gl.createProgram();
    gl.attachShader(prog, vert);
    gl.attachShader(prog, frag);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        const info = gl.getProgramInfoLog(prog);
        gl.deleteProgram(prog);
        console.error(`Program link error: ${info}`);
        exit(1);
    }
    return prog;
}

main().catch(err => {
    console.error(`Fatal: ${err.message}`);
    exit(1);
});
