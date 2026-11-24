(() => {
  const button = document.querySelector(".narsie");
  const singularity = document.querySelector(".singularity");
  const layer = document.querySelector(".character-layer");
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const pullTime = 3;
  const bounceTime = 5;
  const returnTime = 2;
  const fadeTime = 0.6;
  const turn = 2 * Math.PI;

  const mix = (from, to, amount) => from + (to - from) * amount;

  // Fold a straight trajectory back into the window each time it hits an edge.
  function bounce(position, halfSize, size) {
    const span = size - 2 * halfSize;
    if (span <= 0) return size / 2;
    const period = 2 * span;
    const offset = ((position - halfSize) % period + period) % period;
    return halfSize + Math.min(offset, period - offset);
  }

  button.addEventListener("click", () => {
    if (button.getAttribute("aria-disabled") === "true") return;
    button.setAttribute("aria-disabled", "true");
    const reduced = motion.matches;
    singularity.style.opacity = reduced ? 1 : 0;
    singularity.hidden = false;

    // Leave the original CSS animations in place and apply temporary offsets.
    const sprites = reduced ? [] : [...layer.querySelectorAll(".character")].map(element => ({
      element,
      image: element.querySelector("img"),
      dx: 0,
      dy: 0,
    }));
    if (!reduced) layer.classList.add("in-vortex");

    let width, height, start;
    function frame(now) {
      start ??= now;
      const elapsed = (now - start) / 1000;
      const duration = reduced ? pullTime : pullTime + bounceTime + returnTime;
      if (elapsed >= duration || reduced !== motion.matches) {
        singularity.hidden = true;
        singularity.style.removeProperty("opacity");
        for (const sprite of sprites) {
          sprite.element.style.removeProperty("translate");
          sprite.image.style.removeProperty("rotate");
        }
        layer.classList.remove("in-vortex");
        button.removeAttribute("aria-disabled");
        return;
      }

      if (!reduced) {
        // Refresh the paused orbit coordinates if the viewport resizes.
        if (width !== layer.clientWidth || height !== layer.clientHeight) {
          width = layer.clientWidth;
          height = layer.clientHeight;
          for (const sprite of sprites) {
            const rect = sprite.element.getBoundingClientRect();
            sprite.halfWidth = rect.width / 2;
            sprite.halfHeight = rect.height / 2;
            sprite.x = rect.left + sprite.halfWidth - sprite.dx;
            sprite.y = rect.top + sprite.halfHeight - sprite.dy;
          }
        }

        singularity.hidden = elapsed >= pullTime + fadeTime;
        singularity.style.opacity = Math.max(0, Math.min(
          1, elapsed / fadeTime, (pullTime + fadeTime - elapsed) / fadeTime,
        ));
        for (const [index, sprite] of sprites.entries()) {
          const cx = width / 2;
          const cy = height / 2;
          const radius = Math.hypot(sprite.x - cx, sprite.y - cy);
          const angle = Math.atan2(sprite.y - cy, sprite.x - cx);
          const innerRadius = Math.min(radius, 16 + index * 7);
          const pull = Math.min(1, elapsed / pullTime);
          let spin = 3 * turn * pull ** 2;
          let x, y;

          if (elapsed < pullTime) {
            const distance = mix(innerRadius, radius, (1 - pull) ** 3);
            x = cx + distance * Math.cos(angle + spin);
            y = cy + distance * Math.sin(angle + spin);
          } else {
            const flight = elapsed - pullTime;
            const recovery = Math.max(0, (flight - bounceTime) / returnTime);
            const blend = recovery ** 2 * (3 - 2 * recovery);
            // Continue bouncing during recovery, but slow down and blend back to orbit.
            const travel = Math.min(flight, bounceTime) + returnTime * (recovery - recovery ** 2 / 2);
            const speed = Math.max(380, Math.hypot(width, height) * 0.7);
            const distance = innerRadius + travel * speed;
            x = mix(bounce(cx + distance * Math.cos(angle), sprite.halfWidth, width), sprite.x, blend);
            y = mix(bounce(cy + distance * Math.sin(angle), sprite.halfHeight, height), sprite.y, blend);
            spin += turn * 2 * travel;
          }

          sprite.dx = x - sprite.x;
          sprite.dy = y - sprite.y;
          sprite.element.style.translate = `${sprite.dx}px ${sprite.dy}px`;
          sprite.image.style.rotate = `${spin}rad`;
        }
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  });
})();
