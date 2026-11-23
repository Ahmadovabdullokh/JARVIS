(function () {
  const COLORS = {
    starting: "#bfefff",
    ready: "#ffc94d",
    listening: "#ff3b2f",
    processing: "#ff9f43",
    thinking: "#ff9f43",
    speaking: "#ffd166",
    error: "#ff2a1a",
    stopped: "#8d5a3c",
  };

  class Reactor {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.status = "starting";
      this.mic = 0;
      this.time = 0;
      this.started = 0;
      this.particles = Array.from({ length: 34 }, (_, index) => ({
        angle: (index / 34) * Math.PI * 2,
        radius: 74 + (index % 9) * 5,
        speed: 0.05 + (index % 6) * 0.02,
        size: 0.7 + (index % 5) * 0.4,
      }));
      this.resize = this.resize.bind(this);
      this.frame = this.frame.bind(this);
      window.ResizeObserver
        ? new ResizeObserver(this.resize).observe(canvas)
        : window.addEventListener("resize", this.resize);
      this.resize();
    }

    resize() {
      const rect = this.canvas.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      this.width = Math.max(160, rect.width || 220);
      this.height = this.width;
      this.canvas.width = Math.round(this.width * dpr);
      this.canvas.height = Math.round(this.height * dpr);
      this.dpr = dpr;
      if (this.ctx) {
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
      this.draw();
    }

    setStatus(status) {
      this.status = String(status || "ready").toLowerCase();
    }

    setMic(value) {
      this.mic = Math.max(0, Math.min(1, Number(value) || 0));
    }

    start() {
      if (this.started) return;
      this.started = performance.now();
      requestAnimationFrame(this.frame);
    }

    frame(now) {
      this.time = (now - this.started) / 1000;
      if (!document.hidden) {
        this.draw();
      }
      requestAnimationFrame(this.frame);
    }

    draw() {
      const ctx = this.ctx;
      if (!ctx) return;
      const width = this.width;
      const height = this.height;
      const cx = width / 2;
      const cy = height / 2 - 5;
      const scale = width / 220;
      const color = COLORS[this.status] || COLORS.ready;
      const speed =
        {
          listening: 1.0,
          processing: 0.6,
          thinking: 0.4,
          speaking: 1.25,
          error: 0.16,
          stopped: 0.08,
          starting: 0.75,
        }[this.status] || 0.65;
      const amplitude =
        {
          listening: 19,
          processing: 13,
          thinking: 10,
          speaking: 23,
          error: 4,
          stopped: 2,
          starting: 9,
        }[this.status] || 12;
      const isError = this.status === "error";
      const t = this.time * speed;
      const fuzz = isError ? (Math.random() - 0.5) * 6 : 0;
      const pulse = (26 + Math.sin(t * 2.1) * 3 + this.mic * 10) * scale + fuzz;

      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(cx, cy);
      ctx.scale(scale, scale);

      const glow = ctx.createRadialGradient(0, 0, 10, 0, 0, 124);
      glow.addColorStop(0, this.alpha(color, 0.24));
      glow.addColorStop(0.42, this.alpha(color, 0.08));
      glow.addColorStop(1, this.alpha(color, 0));
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(0, 0, 124, 0, Math.PI * 2);
      ctx.fill();

      ctx.save();
      ctx.rotate(t * 0.12);
      ctx.strokeStyle = this.alpha(color, 0.22);
      ctx.lineWidth = 1;
      [108, 100, 92].forEach((radius, index) => {
        ctx.beginPath();
        ctx.setLineDash(index === 1 ? [2, 8] : [1, 6]);
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.stroke();
      });
      ctx.setLineDash([]);
      ctx.restore();

      const segments = 12;
      ctx.save();
      ctx.rotate(-t * 0.3);
      for (let index = 0; index < segments; index += 1) {
        const start = (index / segments) * Math.PI * 2;
        const end = start + (Math.PI * 2) / segments - 0.1;
        ctx.strokeStyle =
          index % 3 === 0
            ? this.alpha(color, 0.85)
            : this.alpha(color, 0.26);
        ctx.lineWidth = index % 3 === 0 ? 2.4 : 1;
        ctx.beginPath();
        ctx.arc(0, 0, 96, start, end);
        ctx.stroke();
      }
      ctx.restore();

      for (let index = 0; index < 4; index += 1) {
        const radius = 64 + index * 9;
        const start = t * (0.4 + index * 0.1) + index * 1.15;
        const end = start + 0.55 + index * 0.1;
        ctx.strokeStyle = this.alpha(color, 0.5 - index * 0.07);
        ctx.lineWidth = index === 0 ? 2 : 1;
        ctx.beginPath();
        ctx.arc(0, 0, radius, start, end);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(0, 0, radius, start + Math.PI, end + Math.PI);
        ctx.stroke();
      }

      ctx.save();
      ctx.rotate(t * 0.18);
      ctx.strokeStyle = this.alpha("#ffc94d", 0.7);
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(0, -54);
      ctx.lineTo(47, 27);
      ctx.lineTo(-47, 27);
      ctx.closePath();
      ctx.stroke();
      ctx.restore();

      ctx.save();
      ctx.rotate(-t * 0.26 + Math.PI);
      ctx.strokeStyle = this.alpha("#ff3b2f", 0.5);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, -40);
      ctx.lineTo(35, 20);
      ctx.lineTo(-35, 20);
      ctx.closePath();
      ctx.stroke();
      ctx.restore();

      const core = ctx.createRadialGradient(-4, -7, 2, 0, 0, pulse * 2.3);
      core.addColorStop(0, "#ffffff");
      core.addColorStop(0.16, this.alpha("#ecfcff", 0.98));
      core.addColorStop(0.4, this.alpha("#bfefff", 0.72));
      core.addColorStop(0.72, this.alpha(color, 0.3));
      core.addColorStop(1, this.alpha(color, 0.01));
      ctx.fillStyle = core;
      ctx.shadowColor = "#bfefff";
      ctx.shadowBlur = 30 + this.mic * 12;
      ctx.beginPath();
      ctx.arc(0, 0, pulse * 2.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.strokeStyle = this.alpha("#ffe7ab", 0.85);
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.arc(0, 0, 17 + Math.sin(t * 1.7) * 1.5, 0, Math.PI * 2);
      ctx.stroke();

      ctx.strokeStyle = this.alpha("#bfefff", 0.5);
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.arc(0, 0, 24 + Math.sin(t * 1.1) * 1.2, 0, Math.PI * 2);
      ctx.stroke();

      this.particles.forEach((particle) => {
        const angle = particle.angle + t * particle.speed;
        const x = Math.cos(angle) * particle.radius;
        const y = Math.sin(angle) * particle.radius;
        const twinkle = 0.45 + 0.4 * Math.sin(t * 2 + particle.angle * 3);
        ctx.fillStyle =
          particle.angle % 2 > 1
            ? this.alpha("#ff3b2f", twinkle)
            : this.alpha("#ffc94d", twinkle);
        ctx.beginPath();
        ctx.arc(x, y, particle.size, 0, Math.PI * 2);
        ctx.fill();
      });

      const marker = t * 1.5;
      ctx.fillStyle = "#ecfcff";
      ctx.shadowColor = "#bfefff";
      ctx.shadowBlur = 14;
      ctx.beginPath();
      ctx.arc(
        Math.cos(marker) * 100,
        Math.sin(marker) * 100,
        2.4,
        0,
        Math.PI * 2
      );
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.restore();

      const count = 27;
      const spacing = (width - 60) / (count - 1);
      const startX = 30;
      const baseY = height - 16;
      for (let index = 0; index < count; index += 1) {
        const wave =
          Math.sin(t * 2.2 + index * 0.5) * amplitude * 0.5 +
          Math.sin(t * 1.1 + index) * 1.6;
        const barHeight = 3 + ((Math.sin(t * 2 + index * 0.7) + 1) / 2) * 7;
        const x = startX + index * spacing;
        ctx.fillStyle =
          index % 4 === 0
            ? this.alpha("#ff3b2f", 0.55)
            : this.alpha("#ffc94d", 0.4);
        ctx.fillRect(x - 0.8, baseY + wave - barHeight, 1.6, barHeight);
      }
    }

    alpha(hex, value) {
      const clean = String(hex).replace("#", "");
      if (clean.length !== 6) return "rgba(255,201,77," + value + ")";
      const red = parseInt(clean.slice(0, 2), 16);
      const green = parseInt(clean.slice(2, 4), 16);
      const blue = parseInt(clean.slice(4, 6), 16);
      return (
        "rgba(" +
        red +
        "," +
        green +
        "," +
        blue +
        "," +
        value +
        ")"
      );
    }
  }

  window.JarvisReactor = Reactor;
})();
