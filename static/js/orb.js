// Шейдер адаптирован из предоставленного VoicePoweredOrb без React и OGL.
window.voiceOrb = (() => {
  const canvas = document.getElementById("voice-orb");
  if (!canvas) return { setState() {}, attachStream() {}, detachStream() {} };
  const fallback = { setState() {}, attachStream() {}, detachStream() {} };
  const gl = canvas.getContext("webgl", { alpha: true, antialias: false, premultipliedAlpha: false });
  if (!gl) return fallback;
  const vertex = "attribute vec2 position; varying vec2 vUv; void main(){vUv=(position+1.0)*0.5;gl_Position=vec4(position,0.0,1.0);}";
  const fragment = "precision highp float;\r\n\r\n    uniform float iTime;\r\n    uniform vec3 iResolution;\r\n    uniform float hue;\r\n    uniform float hover;\r\n    uniform float rot;\r\n    uniform float hoverIntensity;\r\n    varying vec2 vUv;\r\n\r\n    vec3 rgb2yiq(vec3 c) {\r\n      float y = dot(c, vec3(0.299, 0.587, 0.114));\r\n      float i = dot(c, vec3(0.596, -0.274, -0.322));\r\n      float q = dot(c, vec3(0.211, -0.523, 0.312));\r\n      return vec3(y, i, q);\r\n    }\r\n\r\n    vec3 yiq2rgb(vec3 c) {\r\n      float r = c.x + 0.956 * c.y + 0.621 * c.z;\r\n      float g = c.x - 0.272 * c.y - 0.647 * c.z;\r\n      float b = c.x - 1.106 * c.y + 1.703 * c.z;\r\n      return vec3(r, g, b);\r\n    }\r\n\r\n    vec3 adjustHue(vec3 color, float hueDeg) {\r\n      float hueRad = hueDeg * 3.14159265 / 180.0;\r\n      vec3 yiq = rgb2yiq(color);\r\n      float cosA = cos(hueRad);\r\n      float sinA = sin(hueRad);\r\n      float i = yiq.y * cosA - yiq.z * sinA;\r\n      float q = yiq.y * sinA + yiq.z * cosA;\r\n      yiq.y = i;\r\n      yiq.z = q;\r\n      return yiq2rgb(yiq);\r\n    }\r\n\r\n    vec3 hash33(vec3 p3) {\r\n      p3 = fract(p3 * vec3(0.1031, 0.11369, 0.13787));\r\n      p3 += dot(p3, p3.yxz + 19.19);\r\n      return -1.0 + 2.0 * fract(vec3(\r\n        p3.x + p3.y,\r\n        p3.x + p3.z,\r\n        p3.y + p3.z\r\n      ) * p3.zyx);\r\n    }\r\n\r\n    float snoise3(vec3 p) {\r\n      const float K1 = 0.333333333;\r\n      const float K2 = 0.166666667;\r\n      vec3 i = floor(p + (p.x + p.y + p.z) * K1);\r\n      vec3 d0 = p - (i - (i.x + i.y + i.z) * K2);\r\n      vec3 e = step(vec3(0.0), d0 - d0.yzx);\r\n      vec3 i1 = e * (1.0 - e.zxy);\r\n      vec3 i2 = 1.0 - e.zxy * (1.0 - e);\r\n      vec3 d1 = d0 - (i1 - K2);\r\n      vec3 d2 = d0 - (i2 - K1);\r\n      vec3 d3 = d0 - 0.5;\r\n      vec4 h = max(0.6 - vec4(\r\n        dot(d0, d0),\r\n        dot(d1, d1),\r\n        dot(d2, d2),\r\n        dot(d3, d3)\r\n      ), 0.0);\r\n      vec4 n = h * h * h * h * vec4(\r\n        dot(d0, hash33(i)),\r\n        dot(d1, hash33(i + i1)),\r\n        dot(d2, hash33(i + i2)),\r\n        dot(d3, hash33(i + 1.0))\r\n      );\r\n      return dot(vec4(31.316), n);\r\n    }\r\n\r\n    vec4 extractAlpha(vec3 colorIn) {\r\n      float a = max(max(colorIn.r, colorIn.g), colorIn.b);\r\n      return vec4(colorIn.rgb / (a + 1e-5), a);\r\n    }\r\n\r\n    const vec3 baseColor1 = vec3(0.611765, 0.262745, 0.996078);\r\n    const vec3 baseColor2 = vec3(0.298039, 0.760784, 0.913725);\r\n    const vec3 baseColor3 = vec3(0.062745, 0.078431, 0.600000);\r\n    const float innerRadius = 0.6;\r\n    const float noiseScale = 0.65;\r\n\r\n    float light1(float intensity, float attenuation, float dist) {\r\n      return intensity / (1.0 + dist * attenuation);\r\n    }\r\n\r\n    float light2(float intensity, float attenuation, float dist) {\r\n      return intensity / (1.0 + dist * dist * attenuation);\r\n    }\r\n\r\n    vec4 draw(vec2 uv) {\r\n      vec3 color1 = adjustHue(baseColor1, hue);\r\n      vec3 color2 = adjustHue(baseColor2, hue);\r\n      vec3 color3 = adjustHue(baseColor3, hue);\r\n\r\n      float ang = atan(uv.y, uv.x);\r\n      float len = length(uv);\r\n      float invLen = len > 0.0 ? 1.0 / len : 0.0;\r\n\r\n      float n0 = snoise3(vec3(uv * noiseScale, iTime * 0.5)) * 0.5 + 0.5;\r\n      float r0 = mix(mix(innerRadius, 1.0, 0.4), mix(innerRadius, 1.0, 0.6), n0);\r\n      float d0 = distance(uv, (r0 * invLen) * uv);\r\n      float v0 = light1(1.0, 10.0, d0);\r\n      v0 *= (1.0 - smoothstep(r0, r0 * 1.05, len));\r\n      float cl = cos(ang + iTime * 2.0) * 0.5 + 0.5;\r\n\r\n      float a = iTime * -1.0;\r\n      vec2 pos = vec2(cos(a), sin(a)) * r0;\r\n      float d = distance(uv, pos);\r\n      float v1 = light2(1.5, 5.0, d);\r\n      v1 *= light1(1.0, 50.0, d0);\r\n\r\n      float v2 = (1.0 - smoothstep(mix(innerRadius, 1.0, n0 * 0.5), 1.0, len));\r\n      float v3 = smoothstep(innerRadius, mix(innerRadius, 1.0, 0.5), len);\r\n\r\n      vec3 col = mix(color1, color2, cl);\r\n      col = mix(color3, col, v0);\r\n      col = (col + v1) * v2 * v3;\r\n      col = clamp(col, 0.0, 1.0);\r\n\r\n      return extractAlpha(col);\r\n    }\r\n\r\n    vec4 mainImage(vec2 fragCoord) {\r\n      vec2 center = iResolution.xy * 0.5;\r\n      float size = min(iResolution.x, iResolution.y);\r\n      vec2 uv = (fragCoord - center) / size * 2.0;\r\n\r\n      float angle = rot;\r\n      float s = sin(angle);\r\n      float c = cos(angle);\r\n      uv = vec2(c * uv.x - s * uv.y, s * uv.x + c * uv.y);\r\n\r\n      uv.x += hover * hoverIntensity * 0.1 * sin(uv.y * 10.0 + iTime);\r\n      uv.y += hover * hoverIntensity * 0.1 * sin(uv.x * 10.0 + iTime);\r\n\r\n      return draw(uv);\r\n    }\r\n\r\n    void main() {\r\n      vec2 fragCoord = vUv * iResolution.xy;\r\n      vec4 col = mainImage(fragCoord);\r\n      gl_FragColor = vec4(col.rgb * col.a, col.a);\r\n    }";
  let program, geometry;
  const shaders = [];
  try {
    const shader = (type, code) => {
      const s = gl.createShader(type);
      shaders.push(s);
      gl.shaderSource(s, code);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error("Orb shader");
      return s;
    };
    program = gl.createProgram();
    gl.attachShader(program, shader(gl.VERTEX_SHADER, vertex));
    gl.attachShader(program, shader(gl.FRAGMENT_SHADER, fragment));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("Orb program");
    gl.useProgram(program);
    geometry = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, geometry);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "position");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  } catch {
    shaders.forEach(s => gl.deleteShader(s));
    if (program) gl.deleteProgram(program);
    if (geometry) gl.deleteBuffer(geometry);
    return fallback;
  }
  const uniforms = Object.fromEntries(["iTime","iResolution","hue","hover","rot","hoverIntensity"].map(n => [n,gl.getUniformLocation(program,n)]));
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let state = "connecting", frame = 0, stopped = false, last = 0, time = 0, rotation = 0, level = 0;
  let context = null, analyser = null, inputNode = null, samples = null;
  function detachStream() {
    if (inputNode) inputNode.disconnect();
    if (analyser) analyser.disconnect();
    if (context && context.state !== "closed") context.close().catch(() => {});
    inputNode = analyser = context = samples = null;
  }
  function attachStream(stream) {
    // Источник записи принадлежит client.js: здесь не запрашиваем и не останавливаем микрофон.
    detachStream();
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      context = new AudioCtx();
      if (context.state === "suspended") context.resume().catch(() => {});
      analyser = context.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = .65;
      inputNode = context.createMediaStreamSource(stream);
      inputNode.connect(analyser);
      samples = new Uint8Array(analyser.frequencyBinCount);
    } catch { detachStream(); }
  }
  function draw(now) {
    frame = 0;
    if (stopped || document.hidden) return;
    const dt = Math.min((now-last)/1000 || 0, .05);
    last = now;
    if (!reduced.matches) time += dt;
    let voice = 0;
    if (analyser && samples) {
      analyser.getByteFrequencyData(samples);
      voice = Math.min(1, Math.sqrt(samples.reduce((sum, v) => sum + (v/255)**2, 0) / samples.length) * 4.5);
    }
    // При ответе сфера показывает состояние воспроизведения, а не измерение громкости TTS.
    const target = state === "listening" ? voice : state === "speaking" ? .22 + .15*Math.sin(time*4) : state === "thinking" || state === "recognizing" ? .2 : .03;
    level += (target-level)*.12;
    if (!reduced.matches) rotation += dt*(.12+level*1.7);
    const dpr = Math.min(devicePixelRatio || 1, 1.75);
    const w = Math.max(1, Math.round(canvas.clientWidth*dpr)), h = Math.max(1, Math.round(canvas.clientHeight*dpr));
    if (canvas.width !== w || canvas.height !== h) {canvas.width=w;canvas.height=h;gl.viewport(0,0,w,h);}
    gl.uniform1f(uniforms.iTime, reduced.matches ? 2 : time);
    gl.uniform3f(uniforms.iResolution,w,h,w/h);
    gl.uniform1f(uniforms.hue,state === "listening" ? -12 : 0);
    gl.uniform1f(uniforms.hover,reduced.matches ? 0 : level);
    gl.uniform1f(uniforms.hoverIntensity,.65);
    gl.uniform1f(uniforms.rot,rotation);
    gl.clearColor(0,0,0,0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES,0,3);
    canvas.parentElement.classList.add("webgl-ready");
    if (!reduced.matches) frame=requestAnimationFrame(draw);
  }
  function resume() { if (!frame && !stopped && !document.hidden) {last=performance.now();frame=requestAnimationFrame(draw);} }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {cancelAnimationFrame(frame);frame=0;} else resume();
  });
  window.addEventListener("resize", resume);
  reduced.addEventListener("change",resume);
  canvas.addEventListener("webglcontextlost", event => {
    event.preventDefault();
    stopped=true;cancelAnimationFrame(frame);
    canvas.parentElement.classList.remove("webgl-ready");
  });
  canvas.addEventListener("webglcontextrestored", () => { canvas.parentElement.classList.remove("webgl-ready"); });
  window.addEventListener("pagehide", () => {cancelAnimationFrame(frame);frame=0;detachStream();});
  window.addEventListener("pageshow", resume);
  resume();
  return { setState(next) {state=next;resume();}, attachStream, detachStream };
})();
