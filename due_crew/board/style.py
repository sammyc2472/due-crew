"""The board's stylesheet (_css): both palettes as tokens, the dark set under Anki's night classes.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

from .base import CARD_SHADOW, CARD_SHADOW_HOVER, ROW_CAP, _theme_css, button_reset


def _css(cfg):
    pad = 3 if cfg.get("compact") else 6
    you_bg = "background: var(--dc-you-bg);" if cfg.get("highlight_me", True) else ""
    return f"""
    <style>
    {_theme_css(cfg)}
    #due-crew {{ margin: 18px auto 8px; max-width: 640px; color: var(--dc-ink);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 13px; }}
    /* 3.5.0: Anki's Decks screen sits in a <center> (the board's older parts
       have always been centred by it; a new part says text-align: left
       itself) and gives every button a margin, a shadow and rounded
       corners, which the board's buttons start without */
    {button_reset("#due-crew button", "color: inherit; font-weight: normal;")}
    /* 3.9.6: its boxes and pickers are the board's to draw: macOS draws any control whose
       appearance isn't none in its own look (Liquid Glass) over the board's. Anki's
       `button {{ outline: none !important }}` takes every focus ring: the board's come back */
    #due-crew :where(input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=color]):not([type=file]), select, textarea) {{
      -webkit-appearance: none; appearance: none; text-shadow: none; -webkit-backdrop-filter: none; backdrop-filter: none;
      box-shadow: none; min-height: 0; letter-spacing: normal; line-height: normal; }}
    #due-crew :where(input, select, textarea):focus-visible {{ outline: 2px solid var(--dc-accent); outline-offset: 0; }}
    #due-crew button:focus-visible {{ outline: 2px solid var(--dc-accent) !important; outline-offset: 2px; }}
    #due-crew [role="button"][tabindex]:focus-visible {{ outline: 2px solid var(--dc-accent) !important; outline-offset: 2px; }}
    /* the board is one rounded card — white by day, near-black by night —
       and inside it there are no rules and no fills: rows separate by
       spacing and the you-row highlight alone */
    #due-crew.dc-frame {{ background: var(--dc-bg); border-radius: 12px;
      padding: 16px 18px 10px; }}
    /* 3.8.0: two of them, apart: the You bubble (Due, Plans, Insights) on
       top, and under it the board, your people (Crew, Squads) */
    #due-crew.dc-frame.dc-split {{ background: transparent; padding: 0; border-radius: 0; }}
    #due-crew.dc-split > .du {{ background: var(--dc-bg); margin: 0 0 12px; }}
    #due-crew .dc-sheet {{ background: var(--dc-bg); border-radius: 12px; padding: 16px 18px 10px; }}
    /* 3.9.9 (Sam): each of our cards sits on the page as Anki's deck list does: its shadow at rest, its
       deeper one under the pointer (Anki's own values, deckbrowser.css's `.fancy table`) */
    #due-crew.dc-frame:not(.dc-split), #due-crew.dc-split > .du, #due-crew .dc-sheet {{ box-shadow: {CARD_SHADOW}; }}
    #due-crew.dc-frame:not(.dc-split):hover, #due-crew.dc-split > .du:hover, #due-crew .dc-sheet:hover {{ box-shadow: {CARD_SHADOW_HOVER}; }}
    /* the deck screen is shared with Anki's own styles (26.x paints
       `.fancy table` with a glass fill) and other add-ons' CSS. None of
       them may redecorate this board: no borders, shadows, radii, or fills
       on the table — every rule below is scoped to #due-crew, and nothing
       here touches the page. The table never needs to scroll or be
       clipped: the name column absorbs the slack and ellipsizes. */
    #due-crew, #due-crew table, #due-crew tr, #due-crew th, #due-crew td {{
      border: 0 !important; box-shadow: none !important; outline: 0 !important; }}
    #due-crew table, #due-crew tr, #due-crew th, #due-crew td {{
      border-radius: 0 !important; background: transparent !important; }}
    /* the one fill inside the card: your row (re-asserted after the reset) */
    #due-crew tr.you td {{ {you_bg.replace(";", " !important;") if you_bg else ""} }}
    #due-crew .dc-head {{ display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 8px 10px; margin-bottom: 10px; }}
    /* the pills stay one row; a narrow window puts them under the logo */
    #due-crew .dc-head > span:last-child {{ white-space: nowrap; }}
    #due-crew .dc-title {{ font-size: 15px; font-weight: 700; line-height: 0; }}
    /* 2.10: the logo is the title. Its squares are the board's: the accent,
       and the line colour for the day off. */
    #due-crew .dc-mark {{ display: inline-block; height: 17px; width: auto; vertical-align: middle; }}
    #due-crew .dc-mark .on {{ fill: var(--dc-accent); }}
    #due-crew .dc-mark .off {{ fill: var(--dc-line); }}
    #due-crew .dc-mark .wm {{ fill: var(--dc-mark); }}
    #due-crew .dc-card .dc-mark {{ display: block; height: 17px; margin: 0 auto 8px; }}
    #due-crew .dc-pill {{ display: inline-block; font-size: 11px; font-weight: 700;
      padding: 1px 10px; border: 1px solid var(--dc-line); color: var(--dc-muted); text-decoration: none; }}
    #due-crew .dc-pill.on {{ background: var(--dc-accent); border-color: var(--dc-accent); color: var(--dc-accent-ink); }}
    #due-crew .dc-pill:first-child {{ border-radius: 99px 0 0 99px; }}
    #due-crew .dc-pill:last-child {{ border-radius: 0 99px 99px 0; }}
    #due-crew .dc-pill + .dc-pill {{ border-left: none; }}
    /* the row cap: ten rows, then the view scrolls inside the card. A row
       is the 13px line box (17px in Chromium) plus its padding, the header
       25px — measured in the preview, not assumed. The half row past the
       cap is the cue that there is more. The header stays put and needs a
       fill of its own, since rows slide under it. */
    #due-crew .dc-scroll {{ max-height: {25 + ROW_CAP * (17 + 2 * pad) + (17 + 2 * pad) // 2}px;
      overflow-y: auto; position: relative; }}
    #due-crew .dc-scroll th {{ position: sticky; top: 0; z-index: 1;
      background: var(--dc-bg) !important; }}
    #due-crew table {{ width: 100%; border-collapse: collapse; }}
    #due-crew th {{ padding: 2px 8px 6px; text-align: right; white-space: nowrap; }}
    #due-crew th a {{ color: var(--dc-muted); font-size: 11px; font-weight: 700; text-decoration: none; white-space: nowrap; }}
    #due-crew th a.on {{ color: var(--dc-accent); }}
    #due-crew td {{ padding: {pad}px 8px; white-space: nowrap; }}
    #due-crew td.nm {{ width: 100%; max-width: 0; overflow: hidden !important;
      text-overflow: ellipsis; }}
    #due-crew td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
    /* 3.9.10, one grid (Sam: "The different friend tables all look very different fundamentally"): Crew's and a
       squad's four number columns are one width whatever is in them, so they sit in the same place on every tab */
    #due-crew table[class*="dc-s-"] tr > th:nth-child(n+2), #due-crew table[class*="dc-s-"] td.n {{ width: 62px; min-width: 62px;
      box-sizing: content-box; }}
    #due-crew td.rk {{ width: 30px; color: var(--dc-muted); }}
    #due-crew td.rk:empty {{ width: 0; padding-left: 0; padding-right: 0; }}  /* 3.9.9: no places on the Crew tab; the column is a show-up tick's alone */
    #due-crew th.lt {{ text-align: left; font-weight: 400; }}
    #due-crew th.lt, #due-crew th.sqh {{ color: var(--dc-muted); font-size: 11px; }}
    #due-crew th.sqh {{ text-align: center; padding: 2px 3px 6px; font-weight: 700; }}
    #due-crew th.sqh.on {{ color: var(--dc-accent); }}
    #due-crew td.sqc {{ text-align: center; padding-left: 3px; padding-right: 3px; width: 18px; }}
    #due-crew .sq {{ display: inline-block; width: 12px; height: 12px; border-radius: 2px;
      background: var(--dc-well); vertical-align: middle; }}
    #due-crew .sq.on {{ background: var(--dc-accent); }}
    #due-crew .sq.away {{ background: var(--dc-well); box-shadow: inset 0 0 0 2px var(--dc-accent); opacity: 0.5; }}
    /* 3.9.1 (Sam's pick, "Cheers, clearer"): a cheer is a pill after the name, in place of the faint 🎉
       column at the end; it shows only while the pointer's on the name (or a key's on it), never always
       (Sam: "only show up when scrolling on a name, not persistent all the time") */
    #due-crew a.dc-cpill {{ display: none; margin-left: 6px; padding: 0 8px; border: 1px solid var(--dc-accent); border-radius: 99px;
      color: var(--dc-accent); font-size: 10.5px; font-weight: 700; line-height: 14px; text-decoration: none; white-space: nowrap;
      vertical-align: 1px; margin-top: -3px; margin-bottom: -3px; }}
    #due-crew td.nm:hover a.dc-cpill, #due-crew td.nm:focus-within a.dc-cpill {{ display: inline-block; }}
    /* a long name gives way so its pill is never cut off: it ends a little sooner while the pill shows */
    #due-crew td.nm:hover a.dc-pl, #due-crew td.nm:focus-within a.dc-pl {{
      display: inline-block; max-width: 56%; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom;
      margin-top: -2px; margin-bottom: -2px; position: relative; top: -1px; }}  /* 3.9.10: pointing at a name moves nothing (it grew the row 2px) */
    #due-crew tr.you a.dc-pl {{ max-width: none; }}
    #due-crew a.dc-cpill:hover, #due-crew a.dc-cpill:focus-visible {{ background: var(--dc-accent); color: var(--dc-accent-ink); outline: none; }}
    /* 3.9.9: a cheer waiting for Due Crew to be reachable shows without the pointer, in the foot's warning colour */
    #due-crew tr.ch a.dc-cpill.held {{ display: block; width: max-content; max-width: 100%; margin: 2px 0 0; border-color: var(--dc-hours); color: var(--dc-hours); }}
    @media (max-width: 520px) {{ #due-crew a.dc-cpill.held .ts {{ display: none; }} }}
    #due-crew tr.you td {{ {you_bg} }}
    #due-crew tr.you td.nm {{ font-weight: 700; }}
    #due-crew tr.dim td {{ color: var(--dc-faded); }}
    /* Q3: long-quiet friends, folded into one line until it's clicked */
    #due-crew tr.qh {{ display: none; }}
    #due-crew table.qopen tr.qh {{ display: table-row; }}
    /* 3.9.12, the bench: who's been away longer than yesterday, as Pips asleep under the rows (no line over it) */
    #due-crew .dc-bench {{ display: flex; flex-wrap: wrap; align-items: flex-end; gap: 6px 14px; padding: 10px 10px 4px; text-align: left; }}
    #due-crew .dc-bench .bn {{ display: inline-flex; flex-direction: column; align-items: center; gap: 1px; min-width: 44px; max-width: 76px;
      text-decoration: none; color: var(--dc-muted); font-size: 11px; line-height: 1.25; opacity: .62; transition: opacity .15s; }}
    #due-crew .dc-bench a.bn:hover, #due-crew .dc-bench a.bn:focus-visible {{ opacity: 1; }}
    #due-crew .dc-bench .dc-rsev {{ display: block; line-height: 0; margin: 8px 0 7px; --sv-a: var(--rs-l); }}
    #due-crew .dc-bench .sv-z {{ display: none; }}  /* asleep, quietly (SC: "without the zzz") */
    #due-crew .dc-bench .bm {{ max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--dc-ink); }}
    #due-crew .dc-bench .bw {{ white-space: nowrap; }}
    #due-crew .dc-bench .bi {{ display: grid; place-items: center; width: 26px; height: 26px; border-radius: 7px; font-weight: 700; font-size: 12px;
      color: #fff; background: var(--rs-l); }}
    #due-crew .dc-bench .more {{ align-self: center; opacity: 1; }}
    #due-crew tr.qfold td {{ text-align: left; }}
    #due-crew tr.qfold a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .la {{ font-size: 10px; margin-left: 5px; }}
    #due-crew small.nwh {{ display: block; height: 5.5px; }}
    #due-crew small.nw {{ display: block; font-size: 10px; line-height: 1.1;
                          color: var(--dc-muted); font-weight: 400; }}
    #due-crew .la.fresh {{ color: var(--dc-fresh); }} #due-crew .la.hours {{ color: var(--dc-hours); }}
    #due-crew .la.faded {{ color: var(--dc-faded); }}
    #due-crew .dc-calm {{ display: flex; gap: 10px; align-items: baseline; text-align: left; font-size: 11.5px; color: var(--dc-muted);
        padding: 8px 4px 0; margin-top: 6px; border-top: 1px solid var(--dc-line); }}
    #due-crew .dc-calm b {{ color: var(--dc-ink); font-weight: 600; }}
    #due-crew .dc-calm .sp {{ flex: 1; }}
    #due-crew .dc-calm a {{ color: var(--dc-accent); text-decoration: none; font-weight: 600; white-space: nowrap; }}
    #due-crew .dc-calm a.x {{ color: var(--dc-muted); font-weight: 400; }}
    #due-crew .dc-foot {{ display: flex; gap: 10px; font-size: 10.5px; color: var(--dc-muted); padding: 8px 4px 0; }}
    #due-crew .dc-foot .sp {{ flex: 1; }}
    #due-crew .dc-foot .fl, #due-crew .dc-foot .fr {{ display: inline-flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; }}
    #due-crew .dc-foot a.pb {{ border: 1px solid var(--dc-accent); border-radius: 99px; padding: 1px 9px; }}
    #due-crew .dc-foot a.pb.on {{ background: var(--dc-accent); color: var(--dc-bg); }}
    #due-crew .dc-foot a.warn {{ color: var(--dc-hours); }}
    #due-crew .dc-foot a.ic {{ color: var(--dc-muted); font-weight: 400; font-size: 13px; display: inline-flex; align-items: center;
      vertical-align: middle; padding: 2px; }}
    #due-crew .dc-foot a.ic svg {{ display: block; }}
    #due-crew .dc-foot a.ic:hover {{ color: var(--dc-ink); }}
    #due-crew .dc-wrap[hidden] {{ display: none; }}
    #due-crew .dc-wrap a.wn {{ color: var(--dc-muted); text-decoration: none; font-size: 11px; white-space: nowrap; margin-left: 8px; }}
    #due-crew .dc-empty {{ border: 1px dashed var(--dc-accent); border-radius: 10px; padding: 12px 14px; margin: 8px 0 2px;
      display: grid; gap: 8px; font-size: 12px; }}
    #due-crew .dc-empty .row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
    #due-crew .dc-empty .dc-code {{ font-size: 18px; letter-spacing: 3px; }}
    #due-crew .dc-empty input {{ flex: 1 1 160px; font: inherit; padding: 4px 8px; border: 1px solid var(--dc-line);
      border-radius: 6px; background: var(--dc-bg); color: var(--dc-ink); }}
    #due-crew .dc-empty a.bt {{ border: 1px solid var(--dc-accent); border-radius: 6px; padding: 3px 12px; font-weight: 700;
      color: var(--dc-accent); text-decoration: none; }}
    #due-crew .dc-empty a.bt.on {{ background: var(--dc-accent); color: var(--dc-bg); }}
    #due-crew .dc-foot a {{ color: var(--dc-accent); text-decoration: none; font-weight: 700;
      white-space: nowrap; }}
    #due-crew .dc-note {{ font-style: italic; font-size: 11px; }}
    #due-crew a.dc-pl {{ color: inherit; text-decoration: none;
      border-bottom: 1px dotted var(--dc-line); }}
    #due-crew a.dc-pl:hover {{ color: var(--dc-accent); border-bottom-color: var(--dc-accent); }}
    #due-crew .dc-wrap {{ display: flex; align-items: center; gap: 10px;
      border: 1px solid var(--dc-accent); border-radius: 10px; padding: 8px 12px;
      font-size: 12px; margin-bottom: 10px; }}
    #due-crew .dc-wrap .wc {{ margin-left: auto; color: var(--dc-accent);
      text-decoration: none; font-weight: 700; font-size: 10.5px; white-space: nowrap; }}
    /* a banner's second action sits beside the first: two auto margins would split the free space between them */
    #due-crew .dc-wrap .wc + .wc {{ margin-left: 4px; }}
    #due-crew .dc-wrap.cl-earn {{ text-align: left; }}
    #due-crew .dc-wrap .wx {{ color: var(--dc-muted);
      text-decoration: none; font-weight: 700; }}
    #due-crew .dc-wrap.inv {{ text-align: left; }}
    #due-crew .dc-wrap .yn {{ margin-left: auto; display: flex; gap: 12px; white-space: nowrap; }}
    #due-crew .dc-wrap .yn .wc {{ margin-left: 0; font-size: 12px; }}
    #due-crew .dc-delta {{ font-size: 10px; font-weight: 700; color: var(--dc-accent);
      margin-left: 6px; }}
    #due-crew th .hi {{ display: none; }}
    #due-crew .chip {{ font-size: 10px; margin-left: 5px; white-space: nowrap; color: var(--dc-muted); }}
    #due-crew .chip.live {{ color: var(--dc-fresh); font-weight: 700; }}
    #due-crew .chip.exam {{ color: var(--dc-hours); font-weight: 700; }}
    #due-crew .dc-stw {{ position: relative; display: block; max-width: 100%;
      margin: 2px 0 1px; padding-top: 4px; overflow: hidden; line-height: 0; }}
    #due-crew .dc-stw::before {{ content: ""; position: absolute; top: 0; left: 9px;
      border: 4px solid transparent; border-top: 0; border-bottom-color: var(--dc-well); }}
    #due-crew .dc-st {{ display: inline-block; max-width: 100%; box-sizing: border-box;
      padding: 2px 8px; border-radius: 10px; background: var(--dc-well);
      color: var(--dc-muted); font-size: 11px; font-weight: 400; line-height: 1.4;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: top; }}
    #due-crew tr.you .dc-stw::before {{ border-bottom-color: var(--dc-bg); }}
    #due-crew tr.you .dc-st {{ background: var(--dc-bg); font-weight: 400; }}
    #due-crew .dc-wrap.eve {{ border-color: var(--dc-hours); }}
    #due-crew .dc-wrap.off {{ border-color: var(--dc-hours); text-align: left; }}
    /* 2.12: study rooms */
    #due-crew .dc-room {{ display: grid; grid-template-columns: auto 1fr auto; gap: 12px; align-items: center;
      border: 1px solid var(--dc-accent); border-radius: 12px; padding: 10px 12px; margin-bottom: 10px; }}
    #due-crew .dc-room .rg {{ width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center;
      background: conic-gradient(var(--dc-accent) calc(var(--p) * 360deg), var(--dc-line) 0); }}
    #due-crew .dc-room .rg.brk {{ background: conic-gradient(var(--dc-hours) calc(var(--p) * 360deg), var(--dc-line) 0); }}
    #due-crew .dc-room .rg b {{ width: 31px; height: 31px; border-radius: 50%; background: var(--dc-bg);
      display: grid; place-items: center; font-size: 12px; }}
    #due-crew .dc-room .rt {{ display: grid; gap: 4px; min-width: 0; font-size: 12.5px; }}
    #due-crew .dc-room .rt small {{ color: var(--dc-muted); font-size: 11.5px; }}
    #due-crew .dc-room .rb {{ display: flex; gap: 3px; align-items: center; }}
    #due-crew .dc-room .rb i {{ height: 6px; border-radius: 3px; background: var(--dc-line); display: block; position: relative; overflow: hidden; }}
    #due-crew .dc-room .rb i u {{ position: absolute; left: 0; top: 0; bottom: 0; background: var(--dc-accent); display: block; }}
    #due-crew .dc-room .rb em {{ height: 3px; border-radius: 2px; background: var(--dc-hours); opacity: .45; display: block; }}
    #due-crew .dc-room .rw {{ display: flex; gap: 8px; align-items: center; }}
    #due-crew .dc-room .fc {{ display: inline-flex; }}
    #due-crew .dc-room .fc i {{ width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center;
      font-style: normal; font-size: 11px; font-weight: 700; color: var(--dc-accent); border: 2px solid var(--dc-bg);
      background: var(--dc-you-bg); margin-left: -6px; }}
    #due-crew .dc-room .fc i:first-child {{ margin-left: 0; }}
    #due-crew .dc-room .go {{ background: var(--dc-accent); color: var(--dc-accent-ink); border-radius: 7px;
      padding: 4px 12px; font-weight: 700; text-decoration: none; font-size: 12px; }}
    #due-crew .dc-room .lv {{ color: var(--dc-muted); text-decoration: none; font-size: 12px; }}
    #due-crew .dc-wrap .rdot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--dc-accent); flex: none; }}
    #due-crew .dc-foot .warn {{ color: var(--dc-hours); }}
    #due-crew .dg {{ margin-bottom: 12px; }}
    #due-crew .dgh {{ font-size: 12.5px; font-weight: 700; margin: 2px 0 5px; }}
    #due-crew .ihead {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 12px; margin: 0 0 8px; }}
    #due-crew .ihead .dc-sw {{ padding: 0; }}
    #due-crew .ictx {{ text-align: left; font-size: 11.5px; color: var(--dc-muted); }}
    #due-crew .ihead .dc-sw + .ictx {{ margin-left: auto; }}
    #due-crew .ictx b {{ color: var(--dc-ink); }}
    #due-crew .ictx a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    /* 3.8.0, the topic map */
    #due-crew .tmap {{ display: flex; flex-wrap: wrap; gap: 3px; margin-top: 2px; }}
    #due-crew .tmap .tm {{ display: flex; flex-direction: column; justify-content: space-between; min-height: 44px; min-width: 0;
      border-radius: 6px; padding: 5px 7px; text-decoration: none; font-size: 11.5px; font-weight: 600; white-space: normal;
      color: var(--dc-ink); overflow: hidden; }}
    #due-crew .tmap .tm span {{ overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2;
      -webkit-box-orient: vertical; overflow-wrap: anywhere; }}
    #due-crew .tmap .tm b {{ font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    #due-crew .tmap .tm b small {{ font-weight: 500; font-size: 10.5px; opacity: .85; }}
    #due-crew .sw.bar {{ width: 14px; height: 3px; border-radius: 1px; background: var(--dc-ink); opacity: .55; }}
    #due-crew .tmap .tm {{ position: relative; }}
    #due-crew .tmap .tm .tmb {{ position: absolute; left: 0; bottom: 0; height: 3px; background: currentColor; opacity: .45; }}
    #due-crew .tm.sn, #due-crew .sw.sn {{ background: var(--dc-well); color: var(--dc-muted); }}
    #due-crew .dc-wp {{ position: relative; display: inline-flex; align-items: baseline; gap: 2px; color: var(--dc-accent); font-weight: 700;
      text-transform: none; letter-spacing: 0; border-radius: 3px; }}
    #due-crew .dc-wp > i {{ font-style: normal; font-size: 9px; pointer-events: none; }}
    #due-crew .dc-wp > select {{ position: absolute; left: 0; top: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; margin: 0; padding: 0;
      border: 0; font: inherit; -webkit-appearance: none; appearance: none; color-scheme: light dark; background: transparent; }}
    #due-crew .dc-wp:focus-within {{ outline: 2px solid var(--dc-accent); outline-offset: 2px; }}
    #due-crew .ik .tmsh {{ margin-left: 8px; color: var(--dc-accent); font-weight: 700; text-decoration: none;
      text-transform: none; letter-spacing: 0; white-space: nowrap; }}
    #due-crew .tmap .tm span i {{ font-style: normal; margin-left: 3px; opacity: .7; }}
    #due-crew .tmt {{ font-size: 11.5px; color: var(--dc-muted); margin: 1px 0 4px; text-align: left; }}
    #due-crew .tmt b {{ color: var(--dc-ink); }}
    #due-crew .tmt a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .tmap .tm:hover {{ filter: brightness(.94); }}
    #due-crew .tm.s3, #due-crew .sw.s3 {{ background: var(--dc-accent); color: var(--dc-accent-ink); }}
    #due-crew .tm.s2 {{ background: color-mix(in srgb, var(--dc-accent) 55%, var(--dc-bg)); }}
    #due-crew .tm.s1 {{ background: color-mix(in srgb, var(--dc-accent) 25%, var(--dc-bg)); }}
    #due-crew .tm.s0, #due-crew .sw.s0 {{ background: var(--dc-hours); color: var(--dc-bg); }}
    #due-crew .iexam {{ position: relative; display: inline-flex; align-items: baseline; gap: 2px; }}
    #due-crew .iexam .q {{ color: var(--dc-muted); font-weight: 400; padding: 0 2px; }}
    #due-crew .iexam input.ixd {{ position: absolute; left: 0; bottom: 0; width: 1px; height: 1px; opacity: 0; border: 0; padding: 0;
      pointer-events: none; }}
    #due-crew .ideck {{ font-size: 13px; color: var(--dc-ink); }}
    #due-crew .ideck + .ictx {{ margin-left: auto; }}
    #due-crew .iexam input {{ font: inherit; color: var(--dc-ink); background: var(--dc-bg); border: 1px solid var(--dc-line);
      border-radius: 6px; padding: 1px 4px; margin: 0; color-scheme: light dark; }}
    /* 3.9.10, one grid: a deck's row as a crew row: Pip and name on the left in the name's place, the same height */
    #due-crew .dr {{ display: flex; align-items: center; gap: 10px; padding: 0 8px; min-height: 34px; font-size: 13px; text-align: left; }}
    #due-crew .dr.me {{ background: var(--dc-you-bg); }}
    #due-crew .dr.me .dn b {{ font-weight: 700; }}
    #due-crew .dn {{ width: 150px; flex-shrink: 0; display: flex; align-items: center; min-width: 0; white-space: nowrap; }}
    #due-crew .dn b {{ font-weight: 400; overflow: hidden; text-overflow: ellipsis; min-width: 0; }}
    #due-crew .dgh {{ text-align: left; padding: 0 8px; }}
    /* 3.9.10: what a tab alone can add (a squad, a shared deck), on that tab under what it adds to, not in the foot
       every tab has (Sam: "specific to those pages and not global functions, otherwise i worry they'd be missed") */
    #due-crew .dc-add {{ text-align: left; padding: 6px 8px 0; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
    #due-crew .dc-add .acts {{ margin-left: auto; font-size: 12px; color: var(--dc-faded); }}
    #due-crew .dc-add .acts a {{ display: inline; border: 0; padding: 0; font-size: 12px; line-height: inherit; border-radius: 0; }}
    #due-crew .dc-add .acts a:hover, #due-crew .dc-add .acts a:focus-visible {{ background: none; color: var(--dc-accent); text-decoration: underline; }}
    #due-crew .dc-add a {{ display: inline-block; color: var(--dc-accent); font-size: 10.5px; font-weight: 700; line-height: 16px;
      text-decoration: none; border: 1px solid var(--dc-accent); border-radius: 99px; padding: 0 8px; }}
    #due-crew .dc-add a:hover, #due-crew .dc-add a:focus-visible {{ background: var(--dc-accent); color: var(--dc-accent-ink); outline: none; }}
    @media (max-width: 520px) {{ #due-crew .dn {{ width: 96px; }} }}
    #due-crew .dtrack {{ position: relative; flex: 1; min-width: 70px; height: 12px; background: var(--dc-well);
      border: 1px solid var(--dc-line); border-radius: 2px; overflow: hidden; }}
    #due-crew .dtrack i {{ position: absolute; left: 0; top: 0; bottom: 0; display: block; }}
    #due-crew .dtrack .fo, #due-crew .dkey .fo {{ opacity: 0.5; background: repeating-linear-gradient(
      135deg, var(--dc-accent) 0 1.5px, transparent 1.5px 5px); }}
    #due-crew .dtrack .fs, #due-crew .dkey .fs {{ background: var(--dc-accent); opacity: 0.35; }}
    #due-crew .dtrack .fm, #due-crew .dkey .fm {{ background: var(--dc-accent); }}
    #due-crew .dkey i {{ display: inline-block; width: 12px; height: 8px; border-radius: 2px; margin: 0 4px 0 10px; vertical-align: 0; }}
    #due-crew .dkey i:first-child {{ margin-left: 0; }}
    #due-crew .dc-count {{ min-width: 118px; flex-shrink: 0; display: flex;
      flex-direction: column; align-items: flex-end; line-height: 1.25;
      white-space: nowrap; font-variant-numeric: tabular-nums; font-size: 11px;
      color: var(--dc-muted); }}
    #due-crew .dc-count .dc-delta {{ margin-left: 0; }}
    #due-crew .dc-line {{ font-size: 11.5px; color: var(--dc-muted); padding: 6px 0; }}
    #due-crew .dc-line a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .dc-live {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%;
      background: var(--dc-accent); box-shadow: 0 0 0 2px var(--dc-you-bg); margin: 0 3px 0 6px;
      vertical-align: 1px; }}
    /* 3.8.0: studying now breathes, slowly; ↻ turns while the board fetches (motion.js) */
    @keyframes dcbreathe {{ from {{ opacity: .4; transform: scale(.85); }} to {{ opacity: 1; transform: scale(1); }} }}
    @keyframes dcspin {{ to {{ transform: rotate(360deg); }} }}
    @media (prefers-reduced-motion: no-preference) {{
      #due-crew .dc-live {{ animation: dcbreathe 2.4s ease-in-out 7 alternate; }}  /* 3.9.1 (Sam's pick D): a few pulses, then lit */
      #due-crew .dc-foot a.ic.dc-spin {{ display: inline-block; animation: dcspin .8s linear infinite; }}
    }}
    #due-crew .dc-plan {{ display: inline-block; width: 36px; height: 4px; border-radius: 2px;
      background: var(--dc-line); overflow: hidden; vertical-align: middle; margin: 0 4px 0 1px; }}
    #due-crew .dc-plan i {{ display: block; height: 100%; background: var(--dc-accent); }}
    #due-crew .dc-flag {{ font-size: 12px; padding: 6px 10px; margin-bottom: 10px; border-radius: 8px;
      background: var(--dc-well); display: flex; flex-wrap: wrap; gap: 4px 10px; }}
    #due-crew .dc-flag a {{ margin-left: auto; color: var(--dc-accent); font-weight: 700;
      text-decoration: none; white-space: nowrap; }}
    #due-crew .dc-flag, #due-crew .dc-flag-h {{ text-align: left; }}
    #due-crew .dc-flag {{ align-items: center; }}
    #due-crew .dc-flag small {{ display: block; color: var(--dc-muted); font-size: 11px; }}
    #due-crew .dc-flag-h {{ font-size: 10.5px; font-weight: 700; letter-spacing: .05em;
      text-transform: uppercase; color: var(--dc-muted); margin: 2px 0 4px; }}
    #due-crew .dc-ask-st + a {{ margin-left: 0; }}
    #due-crew .dc-ask-st {{ margin-left: auto; align-self: center; font-size: 10.5px; font-weight: 700;
      border-radius: 5px; padding: 1px 6px; background: var(--dc-line); white-space: nowrap; }}
    #due-crew .dc-ask-st.on {{ color: var(--dc-accent); }}
    #due-crew .dc-code {{ font-family: Menlo, Consolas, monospace; font-weight: 700;
      letter-spacing: 1.5px; color: var(--dc-ink); }}
    /* a narrow window: headers keep their icons, the last-active chips go
       (a quiet row keeps its: that chip is the whole story), and the name
       gets the room. Until 2.9 every name shrank to three letters. */
    @media (max-width: 560px) {{
      #due-crew th .hl {{ display: none; }} #due-crew th .hi {{ display: inline; }}
      /* 3.9.9 (the design mocks' 3): Crew's numbers keep their words: the column it's sorted by and
         Streak (sorted by Streak: Reviews beside it), so a name has the room four columns took */
      #due-crew table[class*="dc-s-"] th .hl {{ display: inline; }} #due-crew table[class*="dc-s-"] th .hi {{ display: none; }}
      #due-crew table.dc-s-reviews tr > th:nth-child(3), #due-crew table.dc-s-reviews tr > td.n:nth-child(4),
      #due-crew table.dc-s-streak tr > th:nth-child(3), #due-crew table.dc-s-streak tr > td.n:nth-child(4),
      #due-crew table.dc-s-retention tr > th:nth-child(3), #due-crew table.dc-s-retention tr > td.n:nth-child(4),
      #due-crew table.dc-s-reviews tr > th:nth-child(4), #due-crew table.dc-s-reviews tr > td.n:nth-child(5),
      #due-crew table.dc-s-streak tr > th:nth-child(4), #due-crew table.dc-s-streak tr > td.n:nth-child(5),
      #due-crew table.dc-s-time tr > th:nth-child(4), #due-crew table.dc-s-time tr > td.n:nth-child(5),
      #due-crew table.dc-s-time tr > th:nth-child(2), #due-crew table.dc-s-time tr > td.n:nth-child(3),
      #due-crew table.dc-s-retention tr > th:nth-child(2), #due-crew table.dc-s-retention tr > td.n:nth-child(3) {{ display: none; }}
      #due-crew td, #due-crew th {{ padding-left: 4px; padding-right: 4px; }}
      #due-crew tr:not(.dim) .la {{ display: none; }}
      #due-crew .dc-head .dc-mark {{ height: 14px; }}
      #due-crew .dc-room {{ grid-template-columns: auto 1fr; }}
      #due-crew .dc-room .rw {{ grid-column: 1 / -1; justify-content: flex-end; }}
    }}
    #due-crew .dc-sw {{ font-size: 11.5px; padding: 2px 0 8px; }}
    #due-crew .dc-sw a {{ color: var(--dc-muted); text-decoration: none; margin-right: 12px; }}
    #due-crew .dc-sw a.on {{ color: var(--dc-ink); font-weight: 700; box-shadow: inset 0 -2px var(--dc-accent);
      padding-bottom: 2px; }}
    #due-crew .dc-sw a.add {{ color: var(--dc-accent); font-weight: 700; }}
    /* 3.9.10 (Sam: "make sure the spacing on today / week are the same"): a word keeps the room its bold takes,
       so picking one never moves the others */
    #due-crew .dc-sw a[data-t] {{ display: inline-block; padding-bottom: 2px; }}
    #due-crew .dc-sw a[data-t]::after {{ content: attr(data-t); display: block; height: 0; overflow: hidden; visibility: hidden;
      font-weight: 700; }}
    #due-crew .dc-sw a i {{ font-style: normal; font-size: 10px; font-weight: 700; color: var(--dc-accent-ink);
      background: var(--dc-accent); border-radius: 99px; padding: 0 5px; margin-left: 4px; }}
    /* 3.8.0, head row B (Sam's pick): Crew's views, and a squad's names, in
       the table's top-left corner; what was there goes under the table.
       Decks has no table: its picker has a line of its own, with the key */
    #due-crew th.dc-corner {{ text-align: left; white-space: normal; }}
    #due-crew th.dc-corner .dc-sw {{ padding: 0; position: relative; top: 2px; }}
    #due-crew th.dc-corner .dc-sw a {{ display: inline-block; font-size: 11.5px; font-weight: 400; color: var(--dc-muted);
      max-width: 8em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; }}
    #due-crew th.dc-corner .dc-sw a.on {{ color: var(--dc-ink); font-weight: 700; }}
    #due-crew th.dc-corner .dc-sw a.add {{ color: var(--dc-accent); font-weight: 700; }}
    #due-crew .dc-pline {{ display: flex; align-items: baseline; flex-wrap: wrap; gap: 0 10px; text-align: left; padding: 0 8px; }}
    #due-crew .dc-sheet > .dc-sw {{ text-align: left; padding-left: 8px; }}  /* a squad with no table yet */
    @media (max-width: 560px) {{ #due-crew .dc-pline {{ padding: 0 4px; }} #due-crew .dc-sheet > .dc-sw {{ padding-left: 4px; }} }}
    #due-crew .dc-pline .dc-sw {{ padding-bottom: 6px; }}
    #due-crew .dc-pline .dkey {{ margin-left: auto; font-size: 11px; color: var(--dc-muted); }}
    #due-crew .dc-sum {{ text-align: left; padding: 6px 8px 0; }}
    #due-crew .dc-card {{ padding: 16px; text-align: center;
      border-radius: 12px; background: var(--dc-bg); }}
    #due-crew .dc-card b {{ font-size: 15px; display: block; margin-bottom: 5px; }}
    #due-crew .dc-card span {{ font-size: 12px; color: var(--dc-muted); }}
    #due-crew .dc-card a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    /* 3.1: a plan I follow (You › Plans since 3.8.0) */
    #due-crew .dc-pc {{ margin-bottom: 14px; }}
    #due-crew .dc-pc:last-child {{ margin-bottom: 0; }}  /* the box's own padding is the chin under the last card */
    #due-crew .dc-pc .pk {{ display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; margin: 2px 0 6px; }}
    #due-crew .dc-pc .pk b {{ font-size: 12.5px; }}
    #due-crew .dc-pc .pk span {{ font-size: 11px; color: var(--dc-muted); }}
    #due-crew .dc-pc .pk .acts {{ margin-left: auto; display: flex; gap: 12px; }}
    #due-crew .dc-pc .pk .acts a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; font-size: 11.5px; }}
    /* round five: Your plans…, the card's one button, as the head row's was */
    #due-crew .dc-pc .pk .acts a.pbt {{ border: 1px solid var(--dc-line); border-radius: 7px; padding: 3px 10px; }}
    /* round five, pick 3: two or more plans, one at a time: their names a switch in the head */
    #due-crew .dc-pc .psk {{ align-items: center; }}
    #due-crew .dc-pc .psw {{ display: inline-flex; flex-wrap: wrap; max-width: 100%; border: 1px solid var(--dc-line);
      border-radius: 8px; overflow: hidden; }}
    #due-crew .dc-pc .psw a {{ padding: 3px 11px; font-size: 12px; font-weight: 700; color: var(--dc-muted); text-decoration: none;
      white-space: nowrap; max-width: 16em; overflow: hidden; text-overflow: ellipsis; }}
    #due-crew .dc-pc .psw a + a {{ border-left: 1px solid var(--dc-line); }}
    #due-crew .dc-pc .psw a:hover {{ color: var(--dc-ink); }}
    #due-crew .dc-pc .psw a.on {{ background: var(--dc-you-bg); color: var(--dc-ink); }}
    #due-crew .dc-pc .psw .dot {{ display: inline-block; width: 6px; height: 6px; border-radius: 3px; background: var(--dc-hours);
      margin-left: 6px; vertical-align: 2px; }}
    #due-crew .dc-pc .pst {{ font-size: 12px; padding: 6px 0 0; border-top: 1px solid var(--dc-line); margin-top: 6px;
      display: flex; gap: 6px 10px; flex-wrap: wrap; align-items: baseline; }}
    /* 3.9.10, catching up: each day owed a row, Study or Ignore */
    #due-crew .dc-pc .pln {{ font-size: 12px; border-top: 1px solid var(--dc-line); margin-top: 6px; padding-top: 6px; text-align: left; }}
    #due-crew .dc-pc .plh {{ display: flex; gap: 4px 12px; align-items: baseline; flex-wrap: wrap; padding-bottom: 4px; }}
    #due-crew .dc-pc .plh .acts {{ margin-left: auto; }}
    #due-crew .dc-pc .plh a, #due-crew .dc-pc .plr a.ig {{ color: var(--dc-muted); font-weight: 600; text-decoration: none; }}
    #due-crew .dc-pc .plr {{ display: flex; gap: 4px 10px; align-items: baseline; padding: 5px 0; border-top: 1px solid var(--dc-line); }}
    #due-crew .dc-pc .plr .d {{ flex: none; width: 52px; color: var(--dc-muted); }}
    #due-crew .dc-pc .plr b {{ flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .dc-pc .plr .n {{ color: var(--dc-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }}
    #due-crew .dc-pc .plr a {{ white-space: nowrap; }}
    #due-crew .dc-pc .plr a.go {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; border: 1px solid var(--dc-accent);
      border-radius: 99px; padding: 0 9px; }}
    #due-crew .dc-pc .plr a.go.on {{ background: var(--dc-accent); color: var(--dc-accent-ink); }}
    #due-crew .dc-pc .plr.wait b {{ font-weight: 400; color: var(--dc-muted); }}
    #due-crew .dc-pc .plh a:hover, #due-crew .dc-pc .plr a.ig:hover {{ color: var(--dc-ink); }}
    #due-crew .dc-pc .pst .late {{ color: var(--dc-hours); font-weight: 700; }}
    #due-crew .dc-pc .pst .acts {{ margin-left: auto; display: flex; gap: 12px; }}
    #due-crew .dc-pc .pst a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; white-space: nowrap; }}
    /* plans, end to end: the whole plan as a path, a segment a lesson, the exam a diamond at its end */
    #due-crew .ppath {{ display: flex; gap: 3px; align-items: center; height: 12px; margin: 4px 0 3px; }}
    #due-crew .ppath.g2 {{ gap: 2px; }} #due-crew .ppath.g1 {{ gap: 1px; }} #due-crew .ppath.g0 {{ gap: 0; }}
    #due-crew .ppath i {{ flex: 1 1 0; min-width: 0; height: 8px; border-radius: 3px; background: var(--dc-line); display: block; }}
    #due-crew .ppath i[onclick] {{ cursor: pointer; }}
    #due-crew .ppath.fold {{ margin-bottom: 16px; }}
    #due-crew .ppath i.run {{ position: relative; min-width: 34px; }}
    #due-crew .ppath i.run span {{ position: absolute; left: 0; top: 12px; font-size: 10.5px; line-height: 1; font-weight: 400;
      font-style: normal; color: var(--dc-muted); white-space: nowrap; pointer-events: none; }}
    #due-crew .ppath i.run.rl span {{ left: auto; right: 0; }}
    #due-crew .ppath.g1 i, #due-crew .ppath.g0 i {{ border-radius: 1px; }}
    #due-crew .ppath i.d {{ background: var(--dc-accent); }}
    #due-crew .ppath i.b {{ background: var(--dc-hours); }}
    #due-crew .ppath i.c {{ background: var(--dc-accent); opacity: .45; }}
    #due-crew .ppath i.t {{ height: 12px; background: var(--dc-bg); box-shadow: inset 0 0 0 2px var(--dc-accent); }}
    #due-crew .ppath i.d.t {{ background: var(--dc-accent); }}
    #due-crew .ppath i.s {{ background: transparent; box-shadow: inset 0 0 0 1px var(--dc-line); }}
    #due-crew .ppath em {{ flex: none; box-sizing: border-box; width: 9px; height: 9px; margin: 0 2px 0 4px;
      transform: rotate(45deg); border: 2px solid var(--dc-ink); border-radius: 2px; }}
    #due-crew .ppl {{ display: flex; justify-content: space-between; gap: 10px; font-size: 11px; color: var(--dc-muted); }}
    /* 3.9.6: the plan's joys. A segment or line playing one is where its moment starts (motion.js's joy;
       --ago: how long it's been out). Still (Reduce motion), a Pip stands where it lands, then goes */
    #due-crew .ppath i[data-joy] {{ position: relative; }}
    #due-crew .ppath .jpp {{ position: absolute; left: 50%; top: -31px; width: 34px; height: 34px; margin-left: -17px;
      z-index: 3; pointer-events: none; transform-origin: 50% 100%;
      animation: dcjoygo 0s linear calc(5s - var(--ago, 0s)) forwards; }}
    #due-crew .ppath .jpp svg, #due-crew .dc-pc .jgp svg {{ display: block; width: 34px; height: 34px; overflow: visible; }}
    #due-crew .dc-pc .pst .jgo {{ position: relative; display: inline-block; width: 34px; height: 12px; flex: none;
      animation: dcjoygo 0s linear calc(5s - var(--ago, 0s)) forwards; }}
    #due-crew .dc-pc .jgp {{ position: absolute; left: 0; bottom: -3px; width: 34px; height: 34px; pointer-events: none;
      transform-origin: 50% 100%; }}
    @keyframes dcjoygo {{ to {{ visibility: hidden; }} }}
    #due-crew .dc-pc .pst .jd1 {{ color: var(--dc-accent); }}
    #due-crew .dc-pc .pst.jml b, #due-crew .dc-pc .pst.jfin b {{ color: var(--dc-ink); }}
    #due-crew .dc-pc .pst.jcu b {{ color: var(--dc-accent); }}
    #due-crew .dc-pc .pst a.jx {{ color: var(--dc-muted); font-weight: 400; font-size: 15px; line-height: 1; }}
    #due-crew .dc-pc .pst .jta {{ position: relative; display: inline-block; font-size: 13px; line-height: 1; }}
    #due-crew .dc-pc .miss {{ color: var(--dc-hours); font-size: 11px; }}
    #due-crew .dc-pc .n {{ color: var(--dc-muted); font-variant-numeric: tabular-nums; text-align: right;
      white-space: nowrap; font-size: 11px; }}
    #due-crew .dc-pc .pn {{ font-size: 12px; padding: 6px 0 0; border-top: 1px solid var(--dc-line);
      display: flex; gap: 10px; flex-wrap: wrap; margin-top: 6px; }}
    #due-crew .dc-pc .pn.warn {{ color: var(--dc-hours); }}
    #due-crew .dc-pc .pn a {{ margin-left: auto; color: var(--dc-accent); font-weight: 700;
      text-decoration: none; white-space: nowrap; }}
    #due-crew .dc-pc .pn .acts {{ margin-left: auto; display: flex; gap: 12px; flex-wrap: wrap; }}
    #due-crew .dc-pc .pn .acts a {{ margin-left: 0; }}
    /* 3.8.0: at my own pace, Up next */
    #due-crew .dc-pc .pnx {{ text-align: left; margin-top: 4px; }}
    #due-crew .dc-pc .nx {{ display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; justify-content: space-between;
      padding: 7px 10px; border: 1px solid var(--dc-accent); border-radius: 8px; background: var(--dc-you-bg); }}
    #due-crew .dc-pc .nx .nx1 {{ font-size: 12.5px; min-width: 0; overflow-wrap: anywhere; }}
    #due-crew .dc-pc .nx .nx1 small {{ color: var(--dc-muted); font-size: 11.5px; }}
    #due-crew .dc-pc .nx .lbl {{ font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--dc-accent); margin-right: 4px; }}
    #due-crew .dc-pc .nx .nx2 {{ display: flex; gap: 6px; }}
    #due-crew .dc-pc .nx a.bt, #due-crew .dc-pc .nx a.bt2 {{ font-size: 12px; font-weight: 700; text-decoration: none; border-radius: 7px;
      padding: 4px 12px; white-space: nowrap; border: 1px solid var(--dc-accent); }}
    #due-crew .dc-pc .nx a.bt {{ background: var(--dc-accent); color: var(--dc-accent-ink); }}
    #due-crew .dc-pc .nx a.bt2 {{ color: var(--dc-accent); background: transparent; }}
    #due-crew .dc-pc .pq, #due-crew .dc-pc .pnl {{ font-size: 11.5px; color: var(--dc-muted); margin: 6px 2px 0; }}
    #due-crew .dc-pc .pnl {{ color: var(--dc-ink); }}
    #due-crew .dc-pc .pq a, #due-crew .dc-pc .pnl a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .dc-pc .pq a.nx3 {{ font-weight: 600; }}  /* 3.8.1: Then's dates, each opens now */
    /* 3.5.0: a plan's week (Anki centres the Decks screen's text; the plan reads left to right) */
    #due-crew .dc-pc, #due-crew .dc-pways {{ text-align: left; }}
    #due-crew .wbar {{ display: block; height: 5px; background: var(--dc-well); border-radius: 3px; overflow: hidden; }}
    #due-crew .wbar i {{ display: block; height: 100%; background: var(--dc-accent); }}
    #due-crew .pwh {{ display: flex; align-items: center; gap: 10px; font-size: 12px; margin: 8px 0 6px; }}
    #due-crew .pwh .nav {{ display: flex; align-items: center; gap: 8px; }}
    #due-crew .pwh .nav a {{ font-size: 15px; line-height: 20px; }}
    #due-crew .pwh a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .pwh .nav .tb {{ padding: 0 2px; font-size: 12px; font-weight: 700; }}
    #due-crew .pwh .nav .tb.here {{ color: var(--dc-muted); font-weight: 500; }}
    /* 3.9.9 (the design mocks' 1): one action leads. A box's filled button and the one thing it's for
       stay the accent; what's beside them is ink at the same weight, underlined when pointed at */
    #due-crew .dc-foot .fl a:not(.pb):not(.warn), #due-crew .dc-calm a:not(.x),
    #due-crew .du .du-line .acts a, #due-crew .du .du-sg a:not(.x), #due-crew .du .end a.du-go {{ color: var(--dc-ink); font-weight: 600; }}
    #due-crew .dc-foot .fl a:not(.pb):not(.warn):hover, #due-crew .dc-calm a:not(.x):hover,
    #due-crew .du .du-line .acts a:hover, #due-crew .du .du-sg a:not(.x):hover, #due-crew .du .end a.du-go:hover {{ text-decoration: underline; }}
    /* 3.9.9 (the mocks' 6): today keeps the ring; the day opened is filled, its number underlined */
    #due-crew .pwk .pc.sel:not(.now) {{ border-color: var(--dc-faded); box-shadow: none; }}
    #due-crew .pwk .pc.sel:not(.now) .d b {{ text-decoration: underline; text-underline-offset: 3px; }}
    /* 3.9.9: the week across plans, under the plan's card: a row a day, reviews and each plan's new
       cards as one bar, the day's time; a heavy day's line and its one move */
    #due-crew .lw {{ text-align: left; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--dc-line); font-size: 12px; }}
    #due-crew .lwk {{ display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--dc-muted); font-size: 11px; margin-bottom: 6px; }}
    #due-crew .lwk span {{ display: inline-flex; align-items: center; gap: 5px; min-width: 0; }}
    #due-crew .lwk i {{ width: 9px; height: 9px; border-radius: 2px; flex: none; }}
    #due-crew .lwd {{ display: grid; grid-template-columns: 52px minmax(0, 1fr) 56px; gap: 8px; align-items: center; padding: 3px 0; }}
    #due-crew .lwd .d {{ color: var(--dc-muted); white-space: nowrap; }}
    #due-crew .lwd.now .d {{ color: var(--dc-ink); font-weight: 700; }}
    #due-crew .lwd .st {{ display: flex; gap: 2px; height: 10px; min-width: 0; }}
    #due-crew .lwd .st i {{ height: 100%; border-radius: 2px; min-width: 2px; }}
    #due-crew .lwd .n {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--dc-muted); }}
    #due-crew .lwd .n.hv {{ color: var(--dc-hours); font-weight: 700; }}
    #due-crew .lwh {{ display: flex; flex-wrap: wrap; gap: 4px 12px; justify-content: space-between; align-items: baseline;
      margin-top: 8px; padding: 7px 9px; border-radius: 8px; background: var(--dc-well); }}
    #due-crew .lwh a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .lwx {{ color: var(--dc-muted); font-size: 11px; margin-top: 6px; }}
    /* round five, Sam's pick A: the week as seven small days (its bar, what's left, a quiz under its
       day), names in the day's details, which open under the week on a click (motion.js 8) */
    #due-crew .pwk {{ display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }}
    #due-crew .pwk .pc {{ display: grid; gap: 4px; align-content: start; padding: 6px 7px 7px; min-height: 58px; min-width: 0;
      border: 1px solid var(--dc-line); border-radius: 8px; text-align: left; font-size: 11px; cursor: default; }}
    #due-crew .pwk .pc[onclick] {{ cursor: pointer; }}
    #due-crew .pwk .pc[onclick]:hover {{ border-color: var(--dc-faded); }}
    #due-crew .pwk .pc .d {{ color: var(--dc-muted); white-space: nowrap; }}
    #due-crew .pwk .pc .d b {{ color: var(--dc-ink); }}
    #due-crew .pwk .pc.now {{ border-color: var(--dc-accent); box-shadow: inset 0 0 0 1px var(--dc-accent); }}
    #due-crew .pwk .pc.now .d b {{ color: var(--dc-accent); }}
    #due-crew .pwk .pc.past {{ background: var(--dc-well); }}
    #due-crew .pwk .pc.past .wbar {{ background: var(--dc-bg); }}
    #due-crew .pwk .pc.off {{ color: var(--dc-faded); }}
    #due-crew .pwk .pc.off .d b {{ color: var(--dc-faded); }}
    #due-crew .pwk .pc.sel {{ border-color: var(--dc-accent); background: var(--dc-you-bg); box-shadow: inset 0 0 0 1px var(--dc-accent); }}
    #due-crew .pwk .pc .wbar {{ height: 5px; }}
    #due-crew .pwk .pc .wbar.late i {{ background: var(--dc-hours); }}
    #due-crew .pwk .pc .wbar.no {{ background: none; }}
    #due-crew .pwk .pc .n {{ color: var(--dc-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }}
    #due-crew .pwk .pc .late {{ color: var(--dc-hours); font-weight: 700; }}
    #due-crew .pwk .pc .ev {{ font-weight: 700; color: var(--dc-ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      padding-top: 3px; border-top: 1px solid var(--dc-line); }}
    #due-crew .pday {{ border: 1px solid var(--dc-line); border-radius: 10px; padding: 9px 12px 10px; margin-top: 6px;
      display: grid; gap: 8px; font-size: 12px; text-align: left; }}
    #due-crew .pday[hidden] {{ display: none; }}
    #due-crew .pday .ph {{ display: flex; gap: 4px 10px; align-items: baseline; flex-wrap: wrap; }}
    #due-crew .pday .ph > b {{ font-size: 12.5px; }}
    #due-crew .pday .pdl {{ font-size: 11.5px; color: var(--dc-muted); }}
    #due-crew .pday .pu {{ display: grid; gap: 3px; padding-top: 8px; border-top: 1px solid var(--dc-line); }}
    #due-crew .pday .pu .r {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: baseline; }}
    #due-crew .pday .pu .u {{ overflow-wrap: anywhere; }}
    #due-crew .pday .pu .n {{ color: var(--dc-muted); font-size: 11.5px; white-space: nowrap; font-variant-numeric: tabular-nums; }}
    #due-crew .pday .mv {{ color: var(--dc-muted); font-size: 11.5px; }}
    #due-crew .pday .pu .wbar {{ margin: 1px 0 2px; }}
    #due-crew .pday .wi {{ display: grid; gap: 2px; font-size: 11.5px; color: var(--dc-muted); }}
    #due-crew .pday .wi b {{ color: var(--dc-ink); font-weight: 600; }}
    #due-crew .pday .wi .rm {{ font-style: italic; overflow-wrap: anywhere; }}
    #due-crew .pday .acts {{ display: flex; flex-wrap: wrap; gap: 3px 12px; }}
    #due-crew .pday a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .pday a.tp {{ font-weight: 600; }}
    #due-crew .pday .pev {{ display: flex; gap: 4px 12px; flex-wrap: wrap; align-items: baseline; padding-top: 8px; border-top: 1px solid var(--dc-line); }}
    #due-crew .pday .pev .acts {{ margin-left: auto; }}
    #due-crew .pday .ph .acts {{ margin-left: auto; }}
    /* 3.8.1: why a date left cards shut */
    #due-crew .pday .pwhy {{ font-size: 11.5px; color: var(--dc-muted); }}
    #due-crew .pday .pwhy a.tp {{ font-weight: inherit; }}
    /* 3.8.0: a set of cards that opens in Browse (a topic, "16 left"): one look
       everywhere, the board's green, as Today's (Sam: "pick one style and stick with it") */
    #due-crew a.tp {{ color: var(--dc-accent); font-weight: inherit; text-decoration: none; }}
    #due-crew a.tp:hover {{ text-decoration: underline; text-underline-offset: 2px; }}
    #due-crew .pcrew {{ font-size: 11.5px; color: var(--dc-muted); margin-top: 8px; }}
    #due-crew .pcrew a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    /* 3.7.3: a plan's squad (3.8.0: on the Squads tab) */
    #due-crew .tg {{ font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
      color: var(--dc-muted); margin: 12px 0 4px; text-align: left; }}
    #due-crew .tg:first-child {{ margin-top: 2px; }}
    #due-crew .faces {{ display: flex; flex-wrap: wrap; gap: 8px 14px; text-align: left; }}
    #due-crew .face {{ display: grid; justify-items: center; gap: 1px; font-size: 11px; color: var(--dc-muted); min-width: 44px; }}
    #due-crew .face .e {{ font-size: 20px; line-height: 24px; }}
    #due-crew .face .e .dc-rsev {{ margin: 4px 0 0; }}
    #due-crew .face:not(:hover) .dc-rsev .sv, #due-crew .face:not(:hover) .dc-rsev .sv * {{ animation: none !important; }} #due-crew .face:hover .dc-rsev .sv {{ --sv-on: var(--sv-hover, infinite); }}
    #due-crew .ini {{ display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 50%; background: var(--dc-you-bg); color: var(--dc-accent); font-size: 12px; font-weight: 700; line-height: 1; vertical-align: middle; }}
    #due-crew .ini.sm {{ width: 17px; height: 17px; font-size: 10px; }}
    #due-crew .face.away {{ opacity: .38; }}
    #due-crew .face b {{ color: var(--dc-ink); font-weight: 600; font-size: 11.5px; max-width: 64px;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .face.more b {{ color: var(--dc-muted); }}
    #due-crew .tqa {{ display: flex; gap: 6px; align-items: center; margin: 2px 0 6px; }}
    #due-crew .tqa input {{ flex: 1; min-width: 0; font: inherit; font-size: 12.5px; color: var(--dc-ink); background: var(--dc-bg);
      border: 1px solid var(--dc-line); border-radius: 7px; padding: 5px 8px; }}
    #due-crew .tqa a, #due-crew .tq a, #due-crew .tjoin a {{
      color: var(--dc-accent); font-weight: 700; text-decoration: none; font-size: 11.5px; white-space: nowrap; }}
    #due-crew .tq {{ border-top: 1px solid var(--dc-line); padding: 7px 0; margin-top: 0;  /* 3.8.0: rows, not boxes */
      display: grid; gap: 3px; text-align: left; font-size: 12px; overflow-wrap: anywhere; }}
    #due-crew .tq .t {{ display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }}
    #due-crew .tq .t .m {{ margin-left: auto; color: var(--dc-muted); font-size: 11px; white-space: nowrap; }}
    #due-crew .tq .t .acts {{ display: flex; gap: 10px; }}
    #due-crew .tq .t .acts a.q {{ color: var(--dc-muted); font-weight: 500; }}
    #due-crew .tq .card {{ font-size: 11px; color: var(--dc-muted); }}
    #due-crew .tq .rep {{ border-left: 2px solid var(--dc-line); padding-left: 8px; font-size: 11.5px; color: var(--dc-muted); }}
    #due-crew .tq .rep b {{ color: var(--dc-ink); font-weight: 600; }}
    #due-crew .tq .rep .ok {{ color: var(--dc-accent); font-weight: 700; }}
    #due-crew .tq .rep a {{ margin-left: 8px; font-size: 11px; }}
    #due-crew .tq .rep a.q {{ color: var(--dc-muted); font-weight: 500; }}
    #due-crew .tjoin {{ border: 1px solid var(--dc-line); border-radius: 10px; padding: 10px 12px; display: grid; gap: 6px;
      text-align: left; font-size: 12px; }}
    #due-crew .tjoin a.bt {{ justify-self: start; background: var(--dc-accent); color: var(--dc-accent-ink); border-radius: 7px; padding: 4px 12px; }}
    #due-crew .tjoin .k, #due-crew .tq0 {{ color: var(--dc-muted); font-size: 11.5px; text-align: left; }}
    #due-crew .dc-ins {{ display: grid; gap: 14px; text-align: left; font-size: 12px; }}
    #due-crew .dc-ins a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; white-space: nowrap; }}
    #due-crew .dc-ins a.q {{ color: var(--dc-muted); font-weight: 500; }}
    #due-crew .dc-ins a.tp {{ font-weight: inherit; white-space: normal; }}
    #due-crew .ihd {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; text-align: left; }}
    #due-crew .ihd b {{ font-size: 18px; font-variant-numeric: tabular-nums; }}
    #due-crew .ihd > span {{ font-size: 12px; }}
    #due-crew .ihd .m {{ color: var(--dc-muted); }}
    #due-crew .ispark path {{ fill: none; stroke: var(--dc-accent); stroke-width: 2; stroke-linejoin: round; }}
    #due-crew .ispark .end {{ fill: var(--dc-accent); stroke: var(--dc-bg); stroke-width: 2; }}
    #due-crew .ispark .hit, #due-crew .iwk .hit {{ fill: transparent; }}
    #due-crew .ihero {{ background: var(--dc-you-bg); border-radius: 10px; padding: 11px 13px; display: grid; gap: 4px; justify-items: start; }}
    #due-crew .ihero .k {{ font-size: 10.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--dc-accent); }}
    #due-crew .ihero .t {{ font-size: 14px; font-weight: 650; color: var(--dc-ink); }}
    #due-crew .ihero .isc, #due-crew .iline .isc {{ font-size: 11.5px; color: var(--dc-muted); }}
    #due-crew .iline .isc {{ display: inline; }}
    #due-crew .isc a.q {{ margin-left: 2px; }}
    #due-crew .dc-ins a.bt {{ margin-top: 4px; background: var(--dc-accent); color: var(--dc-accent-ink); border-radius: 7px; padding: 5px 13px; font-size: 12px; }}
    #due-crew .isec {{ display: grid; gap: 2px; border-top: 1px solid var(--dc-line); padding-top: 10px; }}
    #due-crew .ik {{ display: flex; flex-wrap: wrap; gap: 4px 0; align-items: baseline; font-size: 10.5px; font-weight: 700;
      letter-spacing: .06em; text-transform: uppercase; color: var(--dc-muted); margin-bottom: 4px; }}
    #due-crew .ik > span {{ text-transform: none; letter-spacing: 0; color: var(--dc-ink); font-weight: 600; }}
    #due-crew .ik .ikey {{ margin-left: auto; padding-left: 12px; color: var(--dc-muted); font-weight: 500; display: inline-flex; gap: 2px 5px; align-items: center;
      flex-wrap: wrap; white-space: nowrap; }}  /* 3.9.2: narrow, it wraps between its parts, never inside one */
    #due-crew .sw {{ display: inline-block; width: 12px; height: 7px; border-radius: 2px; margin-left: 6px; }}
    #due-crew .sw.st {{ background: var(--dc-hours); }}
    #due-crew .sw.fg {{ background: color-mix(in srgb, var(--dc-hours) 40%, var(--dc-bg)); }}
    #due-crew .sw.pm {{ background: color-mix(in srgb, var(--dc-accent) 35%, var(--dc-bg)); }}
    #due-crew .sw.hx {{ background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--dc-accent) 55%, var(--dc-bg)) 0 2px, color-mix(in srgb, var(--dc-accent) 18%, var(--dc-bg)) 2px 4px); }}
    #due-crew .irow {{ display: grid; grid-template-columns: minmax(0, 1fr) 120px 56px 64px; gap: 10px; align-items: center;
      padding: 5px 0; border-bottom: 1px solid var(--dc-line); }}
    #due-crew .irow:last-child {{ border-bottom: 0; }}
    #due-crew .irow .n {{ display: grid; min-width: 0; text-align: left; }}
    #due-crew .irow .n b {{ font-weight: 500; color: var(--dc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      padding-bottom: 2px; }}  /* 3.8.0: room for the name's underline */
    #due-crew .irow .n span {{ font-size: 10.5px; color: var(--dc-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .irow .ib {{ position: relative; height: 9px; border-radius: 5px; background: var(--dc-well); overflow: hidden; }}
    #due-crew .irow .ib i {{ position: absolute; top: 0; bottom: 0; }}
    #due-crew .irow .ib .st {{ left: 0; background: var(--dc-hours); }}
    #due-crew .irow .ib .fg {{ background: color-mix(in srgb, var(--dc-hours) 40%, var(--dc-bg)); }}
    #due-crew .irow .c {{ text-align: right; color: var(--dc-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }}
    #due-crew .irow .c b {{ color: var(--dc-ink); }}
    #due-crew .irow > a {{ text-align: right; }}
    #due-crew .iwk {{ overflow-x: auto; }}
    #due-crew .iwk svg {{ width: 100%; min-width: 460px; height: auto; display: block; overflow: visible; }}
    #due-crew .iwk .pm {{ fill: color-mix(in srgb, var(--dc-accent) 35%, var(--dc-bg)); }}
    #due-crew .iwk .h1 {{ fill: color-mix(in srgb, var(--dc-accent) 18%, var(--dc-bg)); }}
    #due-crew .iwk .h2 {{ fill: color-mix(in srgb, var(--dc-accent) 55%, var(--dc-bg)); }}
    #due-crew .iwk .g {{ stroke: var(--dc-line); stroke-dasharray: 2 3; }}
    #due-crew .iwk .base {{ stroke: var(--dc-line); }}
    #due-crew .iwk text {{ fill: var(--dc-muted); font-size: 10px; text-anchor: middle; }}
    #due-crew .iwk .yl {{ text-anchor: end; font-size: 9px; }}
    #due-crew .iwk .ax.b {{ fill: var(--dc-ink); font-weight: 700; }}
    #due-crew .iwk .ax.d {{ font-size: 9px; opacity: .8; }}
    #due-crew .iwk .ev {{ font-weight: 700; letter-spacing: .04em; }}
    /* 3.9.2, Reviews ahead: done in ink, started solid, new cards striped; never a warning colour */
    #due-crew .dc-ahead, #due-crew .dc-ahead .ahw {{ min-width: 0; }}
    #due-crew .dc-ahead .iwk svg {{ min-width: 560px; }}
    #due-crew .dc-ahead .ahdefs {{ position: absolute; width: 0; height: 0; overflow: hidden; }}
    #due-crew .ahdefs .h1 {{ fill: color-mix(in srgb, var(--dc-accent) 18%, var(--dc-bg)); }}
    #due-crew .ahdefs .h2 {{ fill: color-mix(in srgb, var(--dc-accent) 55%, var(--dc-bg)); }}
    #due-crew .iwk .ps {{ fill: color-mix(in srgb, var(--dc-ink) 16%, var(--dc-bg)); }}
    #due-crew .sw.ps {{ background: color-mix(in srgb, var(--dc-ink) 16%, var(--dc-bg)); }}
    #due-crew .iwk .sep {{ stroke: var(--dc-line); stroke-dasharray: 2 3; }}
    #due-crew .iwk .exl {{ stroke: var(--dc-ink); stroke-width: 1; }}
    #due-crew .iwk .ax.ev {{ fill: var(--dc-ink); font-weight: 700; }}
    #due-crew .dc-ahead .xline {{ color: var(--dc-ink); margin: 2px 0 6px; }}
    #due-crew .dc-ahead .xline b {{ font-variant-numeric: tabular-nums; }}
    #due-crew .xwhat {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
    #due-crew .xc {{ border: 1px solid var(--dc-line); border-radius: 99px; padding: 2px 10px; color: var(--dc-ink); cursor: pointer;
      font-size: 11.5px; user-select: none; }}
    #due-crew .xc.on {{ border-color: var(--dc-accent); box-shadow: inset 0 0 0 1px var(--dc-accent); color: var(--dc-accent); font-weight: 700; }}
    #due-crew .xc:focus-visible {{ outline: 2px solid var(--dc-accent); outline-offset: 2px; }}
    #due-crew .xact {{ display: flex; align-items: center; justify-content: space-between; gap: 6px 12px; flex-wrap: wrap;
      font-size: 11.5px; color: var(--dc-muted); margin-top: 6px; text-align: left; }}
    #due-crew .dc-ins .xact a.bt {{ margin-top: 0; }}
    /* 3.9.2, Leeches: one button a card, the rest behind its ⋯ */
    #due-crew .sl-sum {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px 12px;
      font-size: 12.5px; color: var(--dc-ink); text-align: left; }}
    #due-crew .sl-sum b {{ font-variant-numeric: tabular-nums; }}
    #due-crew .sl-hd {{ display: inline-flex; gap: 12px; align-items: center; }}
    #due-crew .sl-row {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 7px 0;
      border-bottom: 1px solid var(--dc-line); }}
    #due-crew .sl-row:last-child {{ border-bottom: 0; }}
    #due-crew .sl-q {{ display: grid; min-width: 0; gap: 1px; text-align: left; }}
    #due-crew .sl-q b {{ font-weight: 500; color: var(--dc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .sl-q span {{ font-size: 10.5px; color: var(--dc-muted); }}
    #due-crew .sl-q .ex {{ color: var(--dc-ink); font-weight: 600; }}
    #due-crew .sl-act {{ display: flex; align-items: center; gap: 10px; justify-content: flex-end; flex-wrap: wrap; }}
    #due-crew .dc-ins a.sl-bt {{ background: var(--dc-accent); color: var(--dc-accent-ink); border-radius: 7px; padding: 3px 10px; font-size: 11.5px; }}
    #due-crew .dc-ins a.sl-bt.tip {{ background: transparent; color: var(--dc-accent); box-shadow: inset 0 0 0 1.5px var(--dc-accent); }}
    #due-crew .sl-more {{ font-size: 11px; display: inline-flex; gap: 8px; align-items: center; }}
    #due-crew .sl-plus {{ font-size: 11px; color: var(--dc-muted); text-align: left; padding: 6px 0 0; }}
    @media (max-width: 560px) {{ #due-crew .sl-row {{ grid-template-columns: minmax(0, 1fr); }} #due-crew .sl-act {{ justify-content: flex-start; }} }}
    #due-crew .iline {{ border-top: 1px solid var(--dc-line); padding-top: 10px; color: var(--dc-ink); }}
    @media (max-width: 560px) {{ #due-crew .irow {{ grid-template-columns: minmax(0, 1fr) auto auto; row-gap: 4px; }}
      #due-crew .irow .ib {{ grid-column: 1 / -1; grid-row: 2; }} }}
    /* plans, end to end (frame 1): a plan's code or link with Follow, my exam, a plan of my own */
    #due-crew .dc-pways {{ display: grid; gap: 8px; margin: 4px 0 4px; font-size: 12.5px; }}
    #due-crew .dc-pways .pfw {{ display: flex; gap: 8px; align-items: center; }}
    #due-crew .dc-pways input {{ flex: 1; font: inherit; font-size: 12.5px; height: 30px; padding: 0 10px; border: 1px solid var(--dc-line);
      border-radius: 8px; background: var(--dc-well); color: var(--dc-ink); min-width: 0; box-sizing: border-box; }}
    #due-crew .dc-pways input:focus {{ outline: 2px solid var(--dc-accent); outline-offset: 0; }}
    #due-crew .dc-pways a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; white-space: nowrap; }}
    #due-crew .dc-pways a.pbt {{ border: 1px solid var(--dc-accent); border-radius: 8px; padding: 5px 14px; }}
    #due-crew .dc-pways .pwl {{ display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; padding-top: 8px;
      border-top: 1px solid var(--dc-line); }}
    #due-crew .dc-pways .pwl .mu {{ color: var(--dc-muted); }}
    #due-crew .dc-pways .pwl .acts {{ margin-left: auto; display: flex; flex-wrap: wrap; gap: 4px 14px; }}
    @media (max-width: 560px) {{
      /* the seven days stay seven: their numbers and bars, the words and a quiz's name in the day's details */
      #due-crew .pwk .pc {{ padding: 5px 5px 6px; }}
      #due-crew .pwk .pc .dow, #due-crew .pwk .pc .w, #due-crew .pwk .pc .ev {{ display: none; }}
      #due-crew .pwk .pc.ev1 {{ border-bottom: 3px solid var(--dc-ink); }}
      #due-crew .pwh {{ flex-wrap: wrap; }}
    }}
    </style>
    """
