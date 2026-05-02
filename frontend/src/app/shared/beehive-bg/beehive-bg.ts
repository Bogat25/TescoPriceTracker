import { Component, input, computed } from '@angular/core';

@Component({
  selector: 'app-beehive-bg',
  template: `
    <div style="position:absolute;inset:0;overflow:hidden;pointer-events:none;z-index:0">
      <svg width="100%" height="100%" style="position:absolute;inset:0">
        @for (hex of hexagons; track hex.key) {
          <polygon
            [attr.points]="hex.points"
            fill="none"
            stroke="var(--hex-bg-stroke)"
            stroke-width="1"
            [attr.opacity]="opacity()"
          />
        }
      </svg>
    </div>
  `,
})
export class BeehiveBg {
  opacity = input<number>(0.15);

  readonly hexagons = (() => {
    const s = 28, w = s * 2, h = Math.sqrt(3) * s;
    const result: { key: string; points: string }[] = [];
    for (let r = 0; r < 14; r++) {
      for (let c = 0; c < 28; c++) {
        const x = c * w * 0.75 + (r % 2 === 0 ? 0 : w * 0.375);
        const y = r * h * 0.5;
        const pts = Array.from({ length: 6 }, (_, i) => {
          const a = (Math.PI / 180) * (60 * i - 30);
          return `${x + s * Math.cos(a)},${y + s * Math.sin(a)}`;
        }).join(' ');
        result.push({ key: `${r}-${c}`, points: pts });
      }
    }
    return result;
  })();
}
