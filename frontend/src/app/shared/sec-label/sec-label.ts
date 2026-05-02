import { Component, input } from '@angular/core';

/**
 * Section label with a tiny hex bullet and uppercase bold text.
 */
@Component({
  selector: 'app-sec-label',
  template: `
    <div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.09em;margin-bottom:10px;display:flex;align-items:center;gap:6px"
         [style.color]="accent() || 'var(--text-muted)'">
      <svg width="10" height="12" viewBox="0 0 10 12">
        <polygon points="5,0 10,3 10,9 5,12 0,9 0,3"
                 [attr.fill]="accent() || 'var(--text-muted)'"
                 opacity="0.55"/>
      </svg>
      {{ text() }}
    </div>
  `,
})
export class SecLabel {
  text   = input.required<string>();
  accent = input<string>('');
}
