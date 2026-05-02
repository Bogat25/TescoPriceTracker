import { Component, input, computed } from '@angular/core';

/**
 * Renders a colored ↑/↓ delta badge for price changes.
 * Convention: negative = price dropped = green (good), positive = price rose = red (bad).
 */
@Component({
  selector: 'app-delta-badge',
  template: `
    @if (value() === null || value() === undefined || value() === 0) {
      <span class="font-mono-prices" style="color:var(--text-muted);font-size:13px">—</span>
    } @else {
      <span
        class="font-mono-prices"
        [style.color]="isRise() ? 'var(--hex3)' : 'var(--hex5)'"
        [style.font-size.px]="size()"
        style="font-weight:700"
      >{{ isRise() ? '↑' : '↓' }} {{ absDisplay() }}</span>
    }
  `,
})
export class DeltaBadge {
  /** Price change amount in Ft (or whatever currency unit). */
  value = input<number | null | undefined>(null);
  size  = input<number>(13);

  isRise    = computed(() => (this.value() ?? 0) > 0);
  absDisplay = computed(() => {
    const v = Math.abs(this.value() ?? 0);
    return `${v.toLocaleString('hu-HU')} Ft`;
  });
}
