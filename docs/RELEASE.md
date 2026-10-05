# Publication (by Pixam)

À **chaque release** : publier **Mac + Windows**.

| Asset | Contenu |
|---|---|
| `PSHomebrewDesk-mac.zip` | Source prêt à lancer (`start.command`) |
| `PSHomebrewDesk-windows.zip` | Build `.exe` (PyInstaller) |

## Automatique (recommandé)

1. Bump `version.json`
2. Commit + push `main`
3. `git tag vX.Y.Z && git push origin vX.Y.Z`
4. `gh release create vX.Y.Z --title "…" --notes "…"` (sans assets si besoin)
5. Le workflow **Build Mac + Windows release** s’attache aux deux zips sur le tag

Déclenchement manuel :
```bash
gh workflow run build-release.yml -f tag=vX.Y.Z
```

## Mac local

```bash
scripts/make-mac-zip.sh
# → dist/PSHomebrewDesk-mac.zip
```

## Windows local

```bat
scripts\build-windows.bat
# zippe dist\PSHomebrewDesk\ → PSHomebrewDesk-windows.zip
```

## Signature

- Auteur : **Pixam**
- Ne publie pas `payloads/*.elf`, `vendor/`, ni le cache

## Licence

Voir `LICENSE` (All Rights Reserved — Pixam).
