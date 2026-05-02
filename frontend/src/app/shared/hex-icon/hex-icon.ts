import { Component, input } from '@angular/core';

@Component({
  selector: 'app-hex-icon',
  template: `
    <svg
      [attr.width]="size()"
      [attr.height]="svgHeight()"
      [attr.viewBox]="'0 0 ' + size() + ' ' + svgHeight()"
      style="flex-shrink:0;display:block"
    >
      <polygon
        [attr.points]="points()"
        [attr.fill]="accent() + '22'"
        [attr.stroke]="accent()"
        stroke-width="1.5"
      />
      <text
        [attr.x]="size() / 2"
        [attr.y]="svgHeight() * 0.66"
        text-anchor="middle"
        [attr.fill]="accent()"
        [attr.font-size]="size() * 0.38"
        font-weight="700"
        font-family="Nunito Sans, sans-serif"
      >{{ letter() }}</text>
    </svg>
  `,
})
export class HexIcon {
  letter  = input.required<string>();
  accent  = input<string>('#00539F');
  size    = input<number>(32);

  svgHeight() {
    return Math.round(this.size() * 37 / 32);
  }

  points(): string {
    const s = this.size();
    const h = this.svgHeight();
    return `${s/2},0 ${s},${h*.25} ${s},${h*.75} ${s/2},${h} 0,${h*.75} 0,${h*.25}`;
  }
}
