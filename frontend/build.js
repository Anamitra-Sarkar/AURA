const fs = require("fs");
const path = require("path");

const dist = path.join(__dirname, "dist");
fs.mkdirSync(dist, { recursive: true });
fs.writeFileSync(path.join(dist, "index.html"), `<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AURA</title></head>
  <body style="background:#0f0f0f;color:#e8e8e8;font-family:Inter,system-ui,sans-serif;margin:0;padding:2rem">
    <h1>AURA — The AI that works for you</h1>
    <p>Free. Open-source. Runs on your PC or anywhere.</p>
    <p>Connect your PC with <code>pip install aura-client</code></p>
  </body>
</html>`);
