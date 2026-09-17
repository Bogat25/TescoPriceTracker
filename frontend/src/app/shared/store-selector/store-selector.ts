import { Component, OnInit, inject, output } from '@angular/core';
import { StoresService } from '../../services/stores.service';
import { TranslatePipe } from '../translate.pipe';
import { storeAccent } from '../store-accent';

/** Store chips; hidden when only one store is enabled. Emits after every change. */
@Component({
  selector: 'app-store-selector',
  imports: [TranslatePipe],
  template: `
    @if (stores.showSelector()) {
      <div class="ss-wrap" role="group" [attr.aria-label]="'stores.label' | translate">
        <span class="ss-label">{{ 'stores.label' | translate }}</span>
        @for (store of stores.stores(); track store.id) {
          <button type="button" class="ss-chip"
                  [class.active]="stores.isSelected(store.id)"
                  [style.--accent]="accent(store.id)"
                  [attr.aria-pressed]="stores.isSelected(store.id)"
                  (click)="toggle(store.id)">
            <span class="ss-dot"></span>{{ store.name }}
          </button>
        }
      </div>
    }
  `,
  styles: [`
    .ss-wrap { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
    .ss-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); margin-right: 4px; }
    .ss-chip {
      display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 999px;
      border: 1px solid var(--border-color); background: var(--surface-card); color: var(--text-secondary);
      font-size: 13px; font-weight: 600; cursor: pointer; transition: background 120ms, border-color 120ms;
    }
    .ss-chip:hover { background: var(--hover-bg); }
    .ss-chip.active { border-color: var(--accent); color: var(--text-primary); }
    .ss-dot { width: 8px; height: 8px; border-radius: 50%; border: 2px solid var(--accent); }
    .ss-chip.active .ss-dot { background: var(--accent); }
  `],
})
export class StoreSelector implements OnInit {
  readonly stores = inject(StoresService);
  readonly changed = output<void>();

  ngOnInit(): void {
    this.stores.load().subscribe();
  }

  accent(id: string): string {
    return storeAccent(id);
  }

  toggle(id: string): void {
    const before = this.stores.storesParam();
    this.stores.toggle(id);
    if (this.stores.storesParam() !== before) this.changed.emit();
  }
}
