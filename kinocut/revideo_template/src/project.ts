import { makeProject } from '@revideo/core';
import Scene from './scene';
import job from './job.json';

export default makeProject({
  scenes: [Scene],
  settings: {
    shared: {
      size: { x: job.width, y: job.height },
    },
    rendering: {
      fps: job.fps,
    },
  },
});
