"use client";

import { useEffect, useRef, useState, type FC } from "react";
import { Renderer, Program, Mesh, Triangle, Vec3 } from "ogl";
import { cn } from "@/lib/utils";

export interface VoicePoweredOrbProps {
  className?: string;
  hue?: number;
  enableVoiceControl?: boolean;
  voiceSensitivity?: number;
  maxRotationSpeed?: number;
  maxHoverIntensity?: number;
  onVoiceDetected?: (detected: boolean) => void;
  /** Reuse the recorder's stream. The caller retains ownership of its tracks. */
  audioStream?: MediaStream | null;
  onMicrophoneError?: (error: unknown) => void;
}

const vert = /* glsl */ `
precision highp float;
attribute vec2 position;
attribute vec2 uv;
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position, 0.0, 1.0); }
`;
const frag = /* glsl */ `
precision highp float;
uniform float iTime;
uniform vec3 iResolution;
uniform float hue;
uniform float hover;
uniform float rot;
uniform float hoverIntensity;
varying vec2 vUv;
vec3 rgb2yiq(vec3 c) {
  return vec3(dot(c, vec3(0.299, 0.587, 0.114)), dot(c, vec3(0.596, -0.274, -0.322)), dot(c, vec3(0.211, -0.523, 0.312)));
}
vec3 yiq2rgb(vec3 c) {
  return vec3(c.x + 0.956*c.y + 0.621*c.z, c.x - 0.272*c.y - 0.647*c.z, c.x - 1.106*c.y + 1.703*c.z);
}
vec3 adjustHue(vec3 color, float hueDeg) {
  float a = hueDeg * 3.14159265 / 180.0;
  vec3 c = rgb2yiq(color);
  return yiq2rgb(vec3(c.x, c.y*cos(a)-c.z*sin(a), c.y*sin(a)+c.z*cos(a)));
}
vec3 hash33(vec3 p3) {
  p3 = fract(p3 * vec3(0.1031, 0.11369, 0.13787));
  p3 += dot(p3, p3.yxz + 19.19);
  return -1.0 + 2.0 * fract(vec3(p3.x+p3.y, p3.x+p3.z, p3.y+p3.z) * p3.zyx);
}
float snoise3(vec3 p) {
  const float K1 = 0.333333333;
  const float K2 = 0.166666667;
  vec3 i = floor(p + (p.x+p.y+p.z)*K1);
  vec3 d0 = p - (i - (i.x+i.y+i.z)*K2);
  vec3 e = step(vec3(0.0), d0-d0.yzx);
  vec3 i1 = e*(1.0-e.zxy);
  vec3 i2 = 1.0-e.zxy*(1.0-e);
  vec3 d1 = d0-(i1-K2);
  vec3 d2 = d0-(i2-K1);
  vec3 d3 = d0-0.5;
  vec4 h = max(0.6-vec4(dot(d0,d0),dot(d1,d1),dot(d2,d2),dot(d3,d3)),0.0);
  vec4 n = h*h*h*h*vec4(dot(d0,hash33(i)),dot(d1,hash33(i+i1)),dot(d2,hash33(i+i2)),dot(d3,hash33(i+1.0)));
  return dot(vec4(31.316),n);
}
vec4 extractAlpha(vec3 c) {
  float a = max(max(c.r,c.g),c.b);
  return vec4(c/(a+1e-5),a);
}
uniform vec3 baseColor1;
uniform vec3 baseColor2;
uniform vec3 baseColor3;
const float innerRadius = 0.6;
const float noiseScale = 0.65;
float light1(float intensity,float attenuation,float dist) { return intensity/(1.0+dist*attenuation); }
float light2(float intensity,float attenuation,float dist) { return intensity/(1.0+dist*dist*attenuation); }
vec4 draw(vec2 uv) {
  vec3 color1=adjustHue(baseColor1,hue),color2=adjustHue(baseColor2,hue),color3=adjustHue(baseColor3,hue);
  float ang=atan(uv.y,uv.x),len=length(uv);
  float invLen=len>0.0?1.0/len:0.0;
  float n0=snoise3(vec3(uv*noiseScale,iTime*0.5))*0.5+0.5;
  float r0=mix(mix(innerRadius,1.0,0.4),mix(innerRadius,1.0,0.6),n0);
  float d0=distance(uv,(r0*invLen)*uv);
  float v0=light1(1.0,10.0,d0);
  v0*=1.0-smoothstep(r0,r0*1.05,len);
  float cl=cos(ang+iTime*2.0)*0.5+0.5;
  float a=iTime*-1.0;
  vec2 pos=vec2(cos(a),sin(a))*r0;
  float d=distance(uv,pos);
  float v1=light2(1.5,5.0,d)*light1(1.0,50.0,d0);
  float v2=1.0-smoothstep(mix(innerRadius,1.0,n0*0.5),1.0,len);
  float v3=smoothstep(innerRadius,mix(innerRadius,1.0,0.5),len);
  vec3 col=mix(color1,color2,cl);
  col=mix(color3,col,v0);
  col=clamp((col+v1)*v2*v3,0.0,1.0);
  return extractAlpha(col);
}
void main() {
  vec2 uv=(vUv*iResolution.xy-iResolution.xy*0.5)/min(iResolution.x,iResolution.y)*2.0;
  float s=sin(rot),c=cos(rot);
  uv=vec2(c*uv.x-s*uv.y,s*uv.x+c*uv.y);
  uv.x+=hover*hoverIntensity*0.1*sin(uv.y*10.0+iTime);
  uv.y+=hover*hoverIntensity*0.1*sin(uv.x*10.0+iTime);
  vec4 col=draw(uv);
  gl_FragColor=vec4(col.rgb*col.a,col.a);
}
`;

export const VoicePoweredOrb: FC<VoicePoweredOrbProps> = (props) => {
  const { className, enableVoiceControl = true, audioStream } = props;
  const container = useRef<HTMLDivElement>(null);
  const latest = useRef(props);
  latest.current = props;
  const analyser = useRef<AnalyserNode | null>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    if (!enableVoiceControl) { latest.current.onVoiceDetected?.(false); return; }
    let cancelled = false;
    let ownedStream: MediaStream | null = null;
    let context: AudioContext | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let node: AnalyserNode | null = null;
    const cleanup = () => {
      if (analyser.current === node) analyser.current = null;
      source?.disconnect();
      node?.disconnect();
      ownedStream?.getTracks().forEach(track => track.stop());
      if (context && context.state !== "closed") void context.close().catch(() => {});
    };
    void (async () => {
      try {
        const stream = audioStream ?? await navigator.mediaDevices.getUserMedia({ audio: true });
        if (!audioStream) ownedStream = stream;
        if (cancelled) { cleanup(); return; }
        context = new AudioContext();
        if (context.state === "suspended") await context.resume();
        if (cancelled) { cleanup(); return; }
        node = context.createAnalyser();
        node.fftSize = 512;
        node.smoothingTimeConstant = 0.3;
        node.minDecibels = -90;
        node.maxDecibels = -10;
        source = context.createMediaStreamSource(stream);
        source.connect(node);
        analyser.current = node;
      } catch (error) {
        cleanup();
        if (!cancelled) latest.current.onMicrophoneError?.(error);
      }
    })();
    return () => { cancelled = true; cleanup(); latest.current.onVoiceDetected?.(false); };
  }, [enableVoiceControl, audioStream]);

  useEffect(() => {
    const host = container.current;
    if (!host) return;
    let renderer: Renderer | undefined;
    let program: Program | undefined;
    let geometry: Triangle | undefined;
    let observer: ResizeObserver | undefined;
    let frame = 0;
    let disposed = false;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const data = new Uint8Array(256);
    const cleanup = () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer?.disconnect();
      geometry?.remove();
      program?.remove();
      renderer?.gl.canvas.remove();
      renderer?.gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
    try {
      renderer = new Renderer({ alpha: true, premultipliedAlpha: true, antialias: true, dpr: Math.min(window.devicePixelRatio || 1, 2) });
      const gl = renderer.gl;
      gl.clearColor(0, 0, 0, 0);
      host.appendChild(gl.canvas);
      geometry = new Triangle(gl);
      // Цвета шара синхронизированы с CSS-токенами темы.
      const palette = getComputedStyle(document.documentElement);
      const themeColor = (token: string) => {
        const hex = palette.getPropertyValue(token).trim().slice(1);
        return new Vec3(...[0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16) / 255) as [number, number, number]);
      };
      program = new Program(gl, {
        vertex: vert, fragment: frag,
        uniforms: { baseColor1: { value: themeColor("--brand") }, baseColor2: { value: themeColor("--brand-accent") }, baseColor3: { value: themeColor("--ink-strong") }, iTime: { value: 0 }, iResolution: { value: new Vec3(1, 1, 1) }, hue: { value: 0 }, hover: { value: 0 }, rot: { value: 0 }, hoverIntensity: { value: 0 } },
      });
      const mesh = new Mesh(gl, { geometry, program });
      const resize = () => {
        if (!host.clientWidth || !host.clientHeight) return;
        renderer!.setSize(host.clientWidth, host.clientHeight);
        program!.uniforms.iResolution.value.set(gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height);
      };
      observer = new ResizeObserver(resize);
      observer.observe(host);
      resize();
      let last = 0, rotation = 0, elapsed = 0, detected = false;
      const render = (time: number) => {
        if (disposed) return;
        const dt = last ? Math.min((time - last) / 1000, 0.05) : 0;
        last = time;
        const p = latest.current;
        let level = 0;
        if (analyser.current) {
          analyser.current.getByteFrequencyData(data);
          level = Math.min(Math.sqrt(data.reduce((sum, value) => sum + (value / 255) ** 2, 0) / data.length) * (p.voiceSensitivity ?? 1.5) * 3, 1);
        }
        if ((level > 0.1) !== detected) { detected = level > 0.1; p.onVoiceDetected?.(detected); }
        if (!media.matches) {
          elapsed += dt;
          rotation += dt * (0.08 + level * (p.maxRotationSpeed ?? 1.2) * 2);
        }
        const u = program!.uniforms;
        u.iTime.value = elapsed;
        u.hue.value = p.hue ?? 0;
        u.rot.value = rotation;
        u.hover.value = media.matches ? 0 : Math.min(level * 2, 1);
        u.hoverIntensity.value = level * (p.maxHoverIntensity ?? 0.8) * 0.8;
        renderer!.render({ scene: mesh });
        frame = requestAnimationFrame(render);
      };
      frame = requestAnimationFrame(render);
    } catch {
      cleanup();
      setFallback(true);
    }
    return cleanup;
  }, []);

  return <div ref={container} aria-hidden="true" className={cn("relative h-full w-full", fallback && "orb-fallback", className)} />;
};
