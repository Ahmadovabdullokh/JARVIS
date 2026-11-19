(function () {
  const COLORS = {
    starting: "#8bf3ff",
    ready: "#3df5a6",
    listening: "#2ee6ff",
    processing: "#ffc857",
    thinking: "#b18cff",
    speaking: "#8bf3ff",
    error: "#ff6b6b",
    stopped: "#7b93ad",
  };

  class Reactor {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.status = "starting";
      this.mic = 0;
      this.time = 0;
      this.started = 0;
      this.particles = Array.from({ length: 28 }, (_, index) => ({
        angle: (index / 28) * Math.PI * 2,
        radius: 72 + (index % 7) * 7,
        speed: 0.06 + (index % 5) * 0.018,
        size: 0.8 + (index % 4) * 0.45,
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
      const cy = height / 2 - 4;
      const color = COLORS[this.status] || COLORS.ready;
      const speed =
        {
          listening: 0.9,
          processing: 0.55,
          thinking: 0.38,
          speaking: 1.15,
          error: 0.15,
          stopped: 0.08,
          starting: 0.7,
        }[this.status] || 0.6;
      const amplitude =
        {
          listening: 17,
          processing: 12,
          thinking: 9,
          speaking: 21,
          error: 4,
          stopped: 2,
          starting: 8,
        }[this.status] || 11;
      const t = this.time * speed;
      const pulse = 28 + Math.sin(t * 2.1) * 3 + this.mic * 9;

      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(cx, cy);

      const glow = ctx.createRadialGradient(0, 0, 8, 0, 0, 118);
      glow.addColorStop(0, this.alpha(color, 0.18));
      glow.addColorStop(0.45, this.alpha(color, 0.06));
      glow.addColorStop(1, this.alpha(color, 0));
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(0, 0, 120, 0, Math.PI * 2);
      ctx.fill();

      ctx.strokeStyle = this.alpha(color, 0.16);
      ctx.lineWidth = 1;
      [104, 94, 84].forEach((radius, index) => {
        ctx.beginPath();
        ctx.setLineDash(index === 1 ? [2, 7] : [1, 5]);
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.stroke();
      });
      ctx.setLineDash([]);

      for (let index = 0; index < 4; index += 1) {
        const radius = 68 + index * 10;
        const start = t * (0.42 + index * 0.1) + index * 1.2;
        const end = start + 0.58 + index * 0.11;
        ctx.strokeStyle = this.alpha(color, 0.48 - index * 0.06);
        ctx.lineWidth = index === 0 ? 2 : 1;
        ctx.beginPath();
        ctx.arc(0, 0, radius, start, end);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(0, 0, radius, start + Math.PI, end + Math.PI);
        ctx.stroke();
      }

      ctx.strokeStyle = this.alpha(color, 0.65);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(0, 0, 58, -Math.PI / 2, -Math.PI / 2 + Math.PI * 1.65);
      ctx.stroke();

      const core = ctx.createRadialGradient(-5, -8, 2, 0, 0, pulse);
      core.addColorStop(0, "#ffffff");
      core.addColorStop(0.2, this.alpha(color, 0.95));
      core.addColorStop(0.62, this.alpha(color, 0.38));
      core.addColorStop(1, this.alpha(color, 0.02));
      ctx.fillStyle = core;
      ctx.shadowColor = color;
      ctx.shadowBlur = 26 + this.mic * 10;
      ctx.beginPath();
      ctx.arc(0, 0, pulse, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.strokeStyle = this.alpha("#ffffff", 0.72);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(0, 0, 19 + Math.sin(t * 1.7) * 1.4, 0, Math.PI * 2);
      ctx.stroke();

      this.particles.forEach((particle) => {
        const angle = particle.angle + t * particle.speed;
        const x = Math.cos(angle) * particle.radius;
        const y = Math.sin(angle) * particle.radius;
        ctx.fillStyle = this.alpha(color, 0.65);
        ctx.beginPath();
        ctx.arc(x, y, particle.size, 0, Math.PI * 2);
        ctx.fill();
      });

      const marker = t * 1.45;
      ctx.fillStyle = color;
      ctx.shadowColor = color;
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc(
        Math.cos(marker) * 96,
        Math.sin(marker) * 96,
        2.5,
        0,
        Math.PI * 2
      );
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.restore();

      const count = 21;
      const spacing = 6;
      const startX = cx - ((count - 1) * spacing) / 2;
      const baseY = height - 18;
      for (let index = 0; index < count; index += 1) {
        const wave =
          Math.sin(t * 2.2 + index * 0.55) * amplitude * 0.5 +
          Math.sin(t * 1.1 + index) * 1.5;
        const y = baseY + wave;
        const size = 1.3 + ((Math.sin(t * 2.2 + index) + 1) / 2) * 1.5;
        ctx.fillStyle = this.alpha(color, 0.2 + (size - 1.3) * 0.28);
        ctx.beginPath();
        ctx.arc(startX + index * spacing, y, size, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    alpha(hex, value) {
      const clean = String(hex).replace("#", "");
      if (clean.length !== 6) return "rgba(46,230,255," + value + ")";
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
