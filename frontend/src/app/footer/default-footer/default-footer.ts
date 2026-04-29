import { Component } from '@angular/core';

@Component({
  selector: 'app-default-footer',
  imports: [],
  templateUrl: './default-footer.html',
  styleUrl: './default-footer.scss',
})
export class DefaultFooter {
  currentYear = new Date().getFullYear();
}
