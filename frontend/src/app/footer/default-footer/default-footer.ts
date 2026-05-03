import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-default-footer',
  imports: [RouterLink],
  templateUrl: './default-footer.html',
  styleUrl: './default-footer.scss',
})
export class DefaultFooter {
  currentYear = new Date().getFullYear();
}
