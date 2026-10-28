# WebSocket File Descriptor Exhaustion and EMFILE

When realtime notification gateway refuses new WebSocket connections with error EMFILE: too many open files, inspect process file descriptor count vs ulimit -n. Adjust systemd LimitNOFILE to 65536 and tune sysctl fs.file-max to handle high concurrent persistent socket connections.
