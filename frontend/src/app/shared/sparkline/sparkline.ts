import { Component, input, computed } from '@angular/core';

@Component({
  selector: 'app-sparkline',
  template: `
    @if (data().length >= 2) {
      <svg
        [attr.width]="width()"
        [attr.height]="height()"
        [attr.viewBox]="'0 0 ' + width() + ' ' + height()"
        style="display:block;flex-shrink:0"
      >
        <defs>
          <linearGradient [attr.id]="gradId" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" [attr.stop-color]="color()" stop-opacity="0.28"/>
            <stop offset="100%" [attr.stop-color]="color()" stop-opacity="0"/>
          </linearGradient>
        </defs>
        <!-- Area fill -->
        <path [attr.d]="areaPath()" [attr.fill]="'url(#' + gradId + ')'"/>
        <!-- Line -->
        <polyline
          [attr.points]="linePoints()"
          fill="none"
          [attr.stroke]="color()"
          stroke-width="1.8"
          stroke-linejoin="round"
          stroke-linecap="round"
        />
      </svg>
    }
  `,
})
export class Sparkline {
  data   = input.required<number[]>();
  color  = input<string>('#3b9eff');
  width  = input<number>(80);
  height = input<number>(28);

  readonly gradId = `spk${Math.random().toString(36).slice(2, 8)}`;

  linePoints = computed(() => {
    const d = this.data(), w = this.width(), h = this.height();
    if (d.length < 2) return '';
    const min = Math.min(...d), max = Math.max(...d), rng = max - min || 1;
    return d.map((v, i) =>
      `${(i / (d.length - 1)) * w},${h - ((v - min) / rng) * (h - 2) - 1}`
    ).join(' ');
  });

  areaPath = computed(() => {
    const pts = this.linePoints();
    if (!pts) return '';
    const w = this.width(), h = this.height();
    const pArr = pts.split(' ');
    return `M ${pArr.join(' L ')} L ${w} ${h} L 0 ${h} Z`;
  });
}
