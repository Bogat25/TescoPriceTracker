import { Pipe, PipeTransform, inject } from '@angular/core';
import { TranslationService } from '../services/translation.service';

/** Usage: {{ 'key' | translate }} — or — [label]="'key' | translate" */
@Pipe({
  name: 'translate',
  standalone: true,
  // pure: false so the template re-evaluates when the language signal changes.
  // Language changes are infrequent so the perf cost is negligible.
  pure: false,
})
export class TranslatePipe implements PipeTransform {
  private ts = inject(TranslationService);
  transform(key: string): string {
    return this.ts.t(key);
  }
}
