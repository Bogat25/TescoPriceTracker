import { Component, input, computed } from '@angular/core';

@Component({
  selector: 'app-hex-kpi',
  template: `
    <div style="display:flex;flex-direction:column;align-items:center;gap:4px">
      <div [style.position]="'relative'" [style.width.px]="110" [style.height.px]="127">
        <svg width="110" height="127" viewBox="0 0 110 127" style="position:absolute;inset:0">
          <!-- Filled background hex -->
          <polygon [attr.points]="innerPoints" [attr.fill]="accent() + '12'" [attr.stroke]="accent()" stroke-width="2.5"/>
          <!-- Tick marks at each vertex -->
          @for (tick of ticks; track $index) {
            <line
              [attr.x1]="tick.x1" [attr.y1]="tick.y1"
              [attr.x2]="tick.x2" [attr.y2]="tick.y2"
              [attr.stroke]="accent()"
              stroke-width="2"
              stroke-linecap="round"
            />
          }
        </svg>
        <div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:0 8px;text-align:center">
          <div
            class="font-mono-prices"
            style="font-size:20px;font-weight:800;line-height:1"
            [style.color]="accent()"
          >{{ value() }}</div>
          <div
            style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;line-height:1.2;opacity:0.75"
            [style.color]="accent()"
          >{{ label() }}</div>
        </div>
      </div>
    </div>
  `,
})
export class HexKpi {
  value  = input.required<string | number>();
  label  = input.required<string>();
  accent = input<string>('#3b9eff');

  private readonly W = 110, H = 127, s = 46, cx = 55, cy = 63;

  get innerPoints(): string {
    return Array.from({ length: 6 }, (_, i) => {
      const a = (Math.PI / 180) * (60 * i - 30);
      return `${this.cx + this.s * Math.cos(a)},${this.cy + this.s * Math.sin(a)}`;
    }).join(' ');
  }

  get ticks() {
    return Array.from({ length: 6 }, (_, i) => {
      const a = (Math.PI / 180) * (60 * i - 30);
      return {
        x1: this.cx + (this.s - 7) * Math.cos(a),
        y1: this.cy + (this.s - 7) * Math.sin(a),
        x2: this.cx + (this.s + 2) * Math.cos(a),
        y2: this.cy + (this.s + 2) * Math.sin(a),
      };
    });
  }
}
