import random
import rich
from rich.console import Console
console = Console(force_terminal=True) 

hoehe = int(input("Wie viele Schichten soll dein Weihnachtsbaum haben? "))

def zeichne_schicht(hoehe: int):

    for i in range(hoehe):
        sterne = 2 * i + 1                # Sterne pro Zeile
        leerzeichen = hoehe - i - 1       # Einrückung nach links für Zentrierung
            
        zeile = " " * leerzeichen
        for _ in range(sterne):
            if random.random() < 0.2:   # 20% Wahrscheinlichkeit für "Kugel"
                    zeile += "[red]0[/red]"
            else:
                    zeile += "[green]*[/green]"

        rich.print(zeile)


def zeichne_stamm():
    leerzeichen_stamm = hoehe - 1
    rich.print (" " * leerzeichen_stamm + "[red]II[/red]")
    rich.print (" " * leerzeichen_stamm + "[red]II[/red]")

zeichne_schicht(hoehe)
zeichne_stamm()