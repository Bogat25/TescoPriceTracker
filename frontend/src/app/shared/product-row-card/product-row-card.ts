import { Component, computed, inject, input } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Offer, ProductRow, bestPriceKind, rowLink } from '../../services/catalog.service';
import { StoresService } from '../../services/stores.service';
import { TranslatePipe } from '../translate.pipe';
import { storeAccent } from '../store-accent';

/** A product card with one price line per store, cheapest first. */
@Component({
  selector: 'app-product-row-card',
  imports: [DecimalPipe, RouterLink, TranslatePipe],
  template: `
    @let r = row();
    <a [routerLink]="link()" class="rc-card">
      <div class="rc-img">
        @if (r.image_url) {
          <img [src]="r.image_url" [alt]="r.name || ''" loading="lazy" referrerpolicy="no-referrer"/>
        } @else {
          <span class="rc-initial">{{ (r.name || '?').charAt(0).toUpperCase() }}</span>
        }
      </div>
      <div class="rc-body">
        <div class="rc-name">{{ r.name }}</div>
        @if (r.brand) { <div class="rc-brand">{{ r.brand }}</div> }
        <ul class="rc-prices">
          @for (offer of r.offers; track offer.ref) {
            <li class="rc-price-line" [class.cheapest]="isCheapest(offer)">
              <span class="rc-store" [style.--accent]="accent(offer.store)">{{ stores.name(offer.store) }}</span>
              @if (offer.effective_price !== null) {
                <span class="rc-price font-mono-prices" [class]="'rc-kind-' + kind(offer)">
                  {{ offer.effective_price | number:'1.0-0' }} Ft
                </span>
                @if (kind(offer) !== 'regular' && offer.prices.regular !== null) {
                  <span class="rc-regular font-mono-prices">{{ offer.prices.regular | number:'1.0-0' }}</span>
                }
                @if (kind(offer) === 'loyalty') {
                  <span class="rc-tag" [title]="'price.loyalty.hint' | translate">{{ 'price.loyalty' | translate }}</span>
                }
              } @else {
                <span class="rc-noprice">{{ 'price.none' | translate }}</span>
              }
              @if (offer.prices.unit_price !== null && offer.prices.unit) {
                <span class="rc-unit">{{ offer.prices.unit_price | number:'1.0-0' }} Ft/{{ offer.prices.unit }}</span>
              }
            </li>
          }
        </ul>
      </div>
    </a>
  `,
  styles: [`
    :host { display: block; height: 100%; }
    .rc-card {
      display: flex; flex-direction: column; height: 100%; text-decoration: none; color: inherit;
      background: var(--surface-card); border: 1px solid var(--border-color); border-radius: 14px;
      overflow: hidden; transition: box-shadow 150ms, transform 150ms;
    }
    .rc-card:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
    .rc-img { aspect-ratio: 1; display: flex; align-items: center; justify-content: center; background: #fff; }
    .rc-img img { width: 100%; height: 100%; object-fit: contain; padding: 10px; }
    .rc-initial { font-size: 28px; font-weight: 800; color: var(--text-muted); }
    .rc-body { padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 4px; flex: 1; }
    .rc-name { font-size: 13px; font-weight: 600; color: var(--text-primary); line-height: 1.3;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .rc-brand { font-size: 11px; color: var(--text-muted); }
    .rc-prices { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
    .rc-price-line { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px; font-size: 12px; padding: 3px 6px; border-radius: 8px; }
    .rc-price-line.cheapest { background: var(--hover-bg); }
    .rc-store { font-size: 11px; font-weight: 700; color: var(--accent); min-width: 48px; }
    .rc-price { font-weight: 700; color: var(--text-primary); }
    .rc-kind-promo { color: #dc2626; }
    .rc-kind-loyalty { color: #b45309; }
    .rc-regular { text-decoration: line-through; color: var(--text-muted); font-size: 11px; }
    .rc-tag { font-size: 10px; font-weight: 700; color: #b45309; }
    .rc-unit { margin-left: auto; font-size: 10px; color: var(--text-muted); }
    .rc-noprice { color: var(--text-muted); }
  `],
})
export class ProductRowCard {
  readonly stores = inject(StoresService);
  readonly row = input.required<ProductRow>();
  readonly link = computed(() => rowLink(this.row()));

  isCheapest(offer: Offer): boolean {
    const r = this.row();
    return r.offers.length > 1 && offer.effective_price !== null && offer.effective_price === r.best_price;
  }

  kind(offer: Offer): string {
    return bestPriceKind(offer.prices) ?? 'regular';
  }

  accent(id: string): string {
    return storeAccent(id);
  }
}
