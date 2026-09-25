# Timelapse Studio – Requirements

**Version:** 0.1 · **Stand:** 2026-09-25 · **Owner:** Murat
**Ziel-Plattform:** TrueNAS Scale (OptiPlex 7060, Docker via Portainer), erreichbar unter `timelapse.<domain>`

> Kurzfassung des Anforderungsdokuments. IDs (Q-, I-, B-, S-, P-, V-, R-, J-, N-) werden im Code und im Plan referenziert.

## 1. Zweck
Self-hosted Webanwendung für Zeitraffer aus großen Bildserien: Immich-ähnlich durchsuchen → Auswahl über Filter/Regeln → Parameter interaktiv → Sofort-Preview → Render-Job mit Fortschritt → Download.
Erster Anwendungsfall: `/mnt/bulk/Timelapse/@Snapshot` (~344.000 JPEGs, ~125 GB, ~6 Monate, Kamera CC400W, flach in einem Verzeichnis).

## 2. Scope MVP
Mehrere Quellen (read-only Mounts + Uploads) · Indexierung (Zeitstempel, Thumbnails, Helligkeit) · virtualisierter Timeline-Browser · nicht-destruktive Auswahl-Pipeline · Live-Kopplung Frames↔fps↔Länge · Browser-Preview + Proxy-Render · Render-Queue mit Fortschritt/ETA/Abbrechen · Download, Projekte, Presets.

## 3. Betrieb
Compose-Stack via Portainer; 1 Image (Backend + Frontend + Worker, inkl. ffmpeg); Traefik (`traefik`-Netz, `websecure`, certresolver `mydnschallenge`, Middlewares rate-limit/authelia/secure-headers); Auth nur Authelia ForwardAuth (`Remote-User` optional); **Mounts getrennt wie bei Immich:** `/config` = `/mnt/apps/timelapse` (DB, Projekte, Settings) · `/media` = `/mnt/bulk/timelapse-studio` (Dataset; thumbs, proxies, uploads, renders, tmp) · Quellen `:ro` unter `/sources/<name>`; Non-Root (PUID/PGID) + Init-Container chown; optional `/dev/dri` (VAAPI/QSV), CPU-Fallback libx264 immer; Parallelität konfigurierbar (Default 1 Job, Threads = Kerne−1).
ENV: `TZ, PUID, PGID, SOURCES_DIR, MAX_PARALLEL_RENDERS, THUMB_SIZE, HWACCEL=none|vaapi|qsv`.

## 4. Quellen & Indexierung
- Q-1 Unterordner von `/sources` = Quellen (aktivierbar, Anzeigename) · Q-2 strikt read-only · Q-3 Uploads per Drag&Drop inkl. ZIP, Fortschritt, Resume (chunked) → Quelle „Uploads/<Album>“ · Q-4 JPEG/PNG/WebP (+HEIC/TIFF optional)
- I-1 Hintergrund-Scan mit Fortschritt (gefunden/indexiert/Fehler/Rate/ETA) · I-2 inkrementell (Pfad+Größe+mtime) · I-3 Zeitstempel: EXIF DateTimeOriginal → Dateinamenmuster (Regex/strftime, Live-Test) → mtime; Reihenfolge pro Quelle · I-4 pro Bild: Pfad, Quelle, Zeit, B/H, Größe, mittlere Helligkeit, opt. pHash · I-5 WebP-Thumbs ~320 px, Priorität sichtbare Bilder · I-6 kaputte Dateien markieren, Scan läuft weiter · I-7 344k Erst-Index inkl. Thumbs < 2 h, Rescan ohne Änderung < 2 min

## 5. Browser
B-1 Tages-gruppiertes, virtualisiertes Grid · B-2 Scrubber Monate/Tage · B-3 4 Zoomstufen · B-4 Lightbox mit Metadaten · B-5 Histogramm Tag/Stunde mit Drag-Auswahl → Datumsfilter · B-6 Mehrfachauswahl (Klick/Shift/Rechteck) → ein-/ausschließen · B-7 Pipeline-Ergebnis im Grid sichtbar, Toggle „nur Auswahl“

## 6. Auswahl-Pipeline
Geordnete, einzeln aktivier-/sortier-/löschbare Regeln, Live-Ergebnis.
S-1 Quellen · S-2 Datumsbereich · S-3 Tageszeitfenster (auch über Mitternacht) · S-4 Wochentage · S-5 jedes n-te (n, Offset) · S-6 ein Bild pro Intervall (erstes / nächstes zu Uhrzeit X / hellstes / Median) · S-7 auf N begrenzen (gleichmäßig über Zeit) · S-8 Helligkeit min/max · S-9 Duplikate per pHash (v1.1) · S-10 manuell ein-/ausgeschlossen · S-11 Reihenfolge
S-20 „X aus Y“ + Mini-Chart pro Tag · S-21 Neuberechnung bei 344k < 1 s

## 7. Video-Parameter
- P-1..P-5 Frames/fps/Länge gekoppelt; Modus „fps fix“ und „Ziellänge fix“ (Vorschlag fps anpassen oder n-tes Bild); Warnungen < 10 / > 60 fps; Halte-Dauer erstes/letztes Bild
- P-10 Auflösung · P-11 Seitenverhältnis/Crop per Maus · P-12 Rotation/Spiegeln · P-13 H.264/H.265/(AV1), MP4 · P-14 Qualitätsstufen + Expertenmodus · P-15 Deflicker · P-16 tmix-Blending · P-17 Zeitstempel-Overlay · P-18 Titel/Abspann · P-19 Fade · P-20 Audio mit Fade-out
- P-30 Presets · P-31 geschätzte Größe/Renderdauer

## 8. Preview
V-1 Canvas-Player aus Thumbs/Proxies in gewählter fps (Play/Pause, Scrubber, Speed, Frame-Step, Zeitstempel; Crop/Rotation/Overlay näherungsweise) · V-2 abschnittsweises Preloading · V-3 Proxy-Render 480p/ultrafast, optional Ausschnitt, höhere Priorität · V-4 inline abspielen

## 9. Render-Jobs
R-1 persistente Queue; nach Neustart laufender Job „abgebrochen – neu starten?“ · R-2 Job-Seite + Header-Dropdown: Status, %, Dauer, ETA, Render-fps, Speed, Phase, Abbrechen (SIGTERM→SIGKILL, Teildateien weg), fertig: Größe/Player/Download/Löschen/Neu rendern, Fehler: Log (200 Zeilen + Download) · R-3 SSE/WebSocket ≥ 1×/s · R-4 Reihenfolge, Abbrechen wartender, Parallelität · R-5 serverseitig unabhängig vom Browser · R-6 optional ntfy + Browser-Notification · R-7 Frameliste in `/data/tmp`, danach löschen · R-8 Dateiname `<projekt>_<YYYYMMDD-HHMM>_<auflösung>_<fps>fps.mp4`, optional Auto-Cleanup

## 10. Projekte
J-1 Quellen + Pipeline + Parameter + Render-Historie · J-2 anlegen/umbenennen/duplizieren/löschen (nie Quellbilder) · J-3 Autosave · J-4 JSON-Export/-Import

## 11. Später
Interpolation, vidstab, Holy-Grail/LUT, Mehrclip-Schnitt, Auto-Neurender, Upload an Immich/Nextcloud, Mehrbenutzer.

## 12. Nicht-funktional
N-1 Deutsch, responsive · N-2 Dark Mode · N-3 keine Internet-Abflüsse · N-4 Originale read-only · N-5 JSON-Logs stdout, `/api/health` · N-6 Auto-Migrationen · N-7 Unit-Tests Pipeline + Zeitlogik, Integrationstest 10 Bilder → MP4 (ffprobe)

## 14. Abnahmekriterien
1. Portainer-Deploy hinter Authelia · 2. `@Snapshot` voll indexiert, Grid flüssig, Scrubber springt · 3. „07–19 Uhr + jedes 20.“ < 1 s, Länge @30 fps korrekt · 4. „Ziellänge 3:00 @30 fps“ → n, ±1 Frame · 5. Browser-Preview ohne Render · 6. 1080p-Render live mit %, Dauer, ETA, fps; Abbruch < 5 s ohne Reste · 7. ffprobe bestätigt Auflösung/fps/Frames; Download · 8. 50 Bilder Upload → Render · 9. Neustart während Render → „abgebrochen/neu starten“, Daten erhalten
