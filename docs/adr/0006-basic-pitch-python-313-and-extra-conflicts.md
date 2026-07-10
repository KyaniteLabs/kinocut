# BasicPitch Manual Optional Integration

`basic-pitch>=0.4` pulls TensorFlow versions that are not currently resolvable for Python 3.13 and cannot be safely advanced to patched Keras/protobuf versions through Dependabot. Keeping it in declared extras makes automated security updates fail before a pull request can be opened.

The BasicPitch bridge remains available as a manual optional integration for Python 3.11 and 3.12 users who specifically need pitch extraction. It is intentionally not installed by `kinocut` extras until the upstream dependency chain can resolve to maintained TensorFlow/Keras/protobuf versions.
