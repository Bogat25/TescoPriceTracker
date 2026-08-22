import { DOCUMENT } from '@angular/common';
import { Injectable, inject } from '@angular/core';
import { Meta, Title } from '@angular/platform-browser';
import { ActivatedRoute, NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs/operators';

const SITE_ORIGIN = 'https://price-tracker.gavaller.com';
const DEFAULT_DESCRIPTION =
  'Track Tesco Hungary product prices, compare price history and promotions, explore shopping analytics, and create free price-drop alerts.';

export interface SeoPage {
  title: string;
  description: string;
  path: string;
  robots?: string;
}

@Injectable({ providedIn: 'root' })
export class SeoService {
  private readonly document = inject(DOCUMENT);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly title = inject(Title);
  private readonly meta = inject(Meta);

  start(): void {
    this.updateFromRoute();
    this.router.events
      .pipe(filter((event): event is NavigationEnd => event instanceof NavigationEnd))
      .subscribe(() => this.updateFromRoute());
  }

  update(page: SeoPage): void {
    const canonicalUrl = new URL(this.normalisePath(page.path), SITE_ORIGIN).toString();
    const robots = page.robots ?? 'index, follow, max-image-preview:large';

    this.title.setTitle(page.title);
    this.setMeta('description', page.description);
    this.setMeta('robots', robots);
    this.setProperty('og:title', page.title);
    this.setProperty('og:description', page.description);
    this.setProperty('og:url', canonicalUrl);
    this.setProperty('og:type', 'website');
    this.setMeta('twitter:card', 'summary');
    this.setMeta('twitter:title', page.title);
    this.setMeta('twitter:description', page.description);
    this.setCanonical(canonicalUrl);
  }

  private updateFromRoute(): void {
    let current = this.route.snapshot;
    while (current.firstChild) current = current.firstChild;

    this.update({
      title: current.title ?? 'Tesco Price Tracker',
      description: current.data['description'] ?? DEFAULT_DESCRIPTION,
      path: this.router.url.split(/[?#]/, 1)[0],
      robots: current.data['robots'],
    });
  }

  private normalisePath(path: string): string {
    const cleanPath = path.split(/[?#]/, 1)[0];
    return cleanPath.startsWith('/') ? cleanPath : `/${cleanPath}`;
  }

  private setMeta(name: string, content: string): void {
    this.meta.updateTag({ name, content });
  }

  private setProperty(property: string, content: string): void {
    this.meta.updateTag({ property, content });
  }

  private setCanonical(url: string): void {
    let link = this.document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (!link) {
      link = this.document.createElement('link');
      link.rel = 'canonical';
      this.document.head.appendChild(link);
    }
    link.href = url;
  }
}
