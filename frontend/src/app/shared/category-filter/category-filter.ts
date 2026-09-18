import { Component, inject, input, output } from '@angular/core';
import { CategoriesService } from '../../services/categories.service';
import { TranslatePipe } from '../translate.pipe';

/**
 * Filter by the shared category vocabulary.
 *
 * Hidden when there is nothing to choose from: the categories are learned from
 * the products the stores share, so an empty list is a normal state (before the
 * first mapping is built) rather than an error to report.
 */
@Component({
  selector: 'app-category-filter',
  imports: [TranslatePipe],
  template: `
    @if (categories.available()) {
      <div class="cf-wrap">
        <label class="cf-label" [attr.for]="id()">{{ 'categories.label' | translate }}</label>
        <select class="cf-select" [id]="id()"
                [value]="categories.selected()"
                (change)="choose($any($event.target).value)">
          <option value="">{{ 'categories.all' | translate }}</option>
          @for (category of categories.categories(); track category.id) {
            <option [value]="category.id">{{ category.name }} ({{ category.products }})</option>
          }
        </select>
        @if (categories.selected()) {
          <button type="button" class="cf-clear" (click)="choose('')">
            {{ 'categories.clear' | translate }}
          </button>
        }
      </div>
    }
  `,
  styles: [`
    .cf-wrap { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
    .cf-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); }
    .cf-select {
      padding: 5px 10px; border-radius: 8px; border: 1px solid var(--border-color);
      background: var(--surface-card); color: var(--text-secondary);
      font-size: 13px; font-weight: 600; cursor: pointer; max-width: 320px;
    }
    .cf-select:hover { background: var(--hover-bg); }
    .cf-clear { background: none; border: 0; padding: 4px 6px; cursor: pointer; font-size: 12px; color: var(--text-muted); text-decoration: underline; }
    .cf-clear:hover { color: var(--text-primary); }
  `],
})
export class CategoryFilter {
  readonly categories = inject(CategoriesService);
  /** Distinct element id, so a page may hold more than one of these. */
  readonly id = input('category-filter');
  readonly changed = output<void>();

  choose(id: string): void {
    if (id === this.categories.selected()) return;
    this.categories.select(id);
    this.changed.emit();
  }
}
