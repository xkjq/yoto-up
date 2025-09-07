import flet as ft
import threading
from pathlib import Path

class IconReplaceDialog:
    def __init__(self, api, card, page, show_snack, show_card_details, kind='chapter', ch_i=None, tr_i=None):
        self.api = api
        self.card = card
        self.page = page
        self.show_snack = show_snack
        self.show_card_details = show_card_details
        self.kind = kind
        self.ch_i = ch_i
        self.tr_i = tr_i
        self.dialog = None

    def open(self):
        default_text = ''
        if self.kind == 'chapter':
            try:
                ch = self.card.get('content', {}).get('chapters', [])[self.ch_i]
                default_text = ch.get('title','') if isinstance(ch, dict) else str(ch)
            except Exception:
                default_text = ''
        else:
            try:
                ch = self.card.get('content', {}).get('chapters', [])[self.ch_i]
                tr = ch.get('tracks', [])[self.tr_i]
                default_text = tr.get('title','') if isinstance(tr, dict) else ''
            except Exception:
                default_text = ''

        search_field = ft.TextField(label='Search text for icons', value=default_text, width=400)
        include_yoto = ft.Checkbox(label='Include YotoIcons', value=True)
        max_searches_field = ft.TextField(label='Max extra searches', value='3', width=120)
        top_n_field = ft.TextField(label='Top N results', value='10', width=120)
        results_list = ft.ListView(expand=True, spacing=6, height=420)

        def do_search(_ev=None):
            def search_worker():
                try:
                    q = (search_field.value or '').strip()
                    try:
                        mx = int(max_searches_field.value or '3')
                    except Exception:
                        mx = 3
                    try:
                        topn = int(top_n_field.value or '5')
                    except Exception:
                        topn = 5
                    inc = bool(include_yoto.value)
                    results_list.controls.clear()
                    self.page.update()
                    icons = self.api.find_best_icons_for_text(q or default_text or ' ', include_yotoicons=inc, max_searches=mx, top_n=topn)
                    if not icons:
                        results_list.controls.append(ft.Text('No icons found', selectable=True))
                    else:
                        for icon in icons:
                            img_src = None
                            try:
                                if icon.get('mediaId'):
                                    p = self.api.get_icon_cache_path(f"yoto:#{icon.get('mediaId')}")
                                    if p and Path(p).exists():
                                        img_src = str(p)
                                if not img_src and icon.get('url'):
                                    img_src = icon.get('url')
                                if not img_src and icon.get('img_url'):
                                    img_src = icon.get('img_url')
                                if not img_src and icon.get('cache_path') and Path(icon.get('cache_path')).exists():
                                    img_src = icon.get('cache_path')
                            except Exception:
                                img_src = None

                            def use_icon(ev2, icon=icon):
                                def use_worker():
                                    self.page.update()
                                    full = self.api.get_card(self.card.get('cardId') or self.card.get('id') or self.card.get('contentId'))
                                    media_id = icon.get('mediaId')
                                    if not media_id and 'id' in icon:
                                        uploaded = self.api.upload_yotoicons_icon_to_yoto_api(icon)
                                        media_id = uploaded.get('mediaId')
                                    if not media_id:
                                        self.show_snack('Selected icon could not be uploaded or has no media id', error=True)
                                        return
                                    if self.kind == 'chapter':
                                        target_ch = full.content.chapters[self.ch_i]
                                        if not getattr(target_ch, 'display', False):
                                            target_ch.display = type(target_ch.display)() if hasattr(target_ch, 'display') else None
                                        target_ch.display.icon16x16 = f"yoto:#{media_id}"
                                    else:
                                        target_ch = full.content.chapters[self.ch_i]
                                        target_tr = target_ch.tracks[self.tr_i]
                                        if not getattr(target_tr, 'display', False):
                                            target_tr.display = type(target_tr.display)() if hasattr(target_tr, 'display') else None
                                        target_tr.display.icon16x16 = f"yoto:#{media_id}"
                                    self.api.update_card(full, return_card_model=False)
                                    self.show_card_details(None, full)
                                threading.Thread(target=use_worker, daemon=True).start()

                            row_children = []
                            if img_src:
                                try:
                                    img = ft.Image(src=img_src, width=48, height=48)
                                    row_children.append(ft.GestureDetector(content=img, on_tap=use_icon))
                                except Exception:
                                    placeholder = ft.Container(width=48, height=48, bgcolor=ft.Colors.GREY_200)
                                    row_children.append(ft.GestureDetector(content=placeholder, on_tap=use_icon, mouse_cursor=ft.MouseCursor.CLICK))
                            else:
                                placeholder = ft.Container(width=48, height=48, bgcolor=ft.Colors.GREY_200)
                                row_children.append(ft.GestureDetector(content=placeholder, on_tap=use_icon, mouse_cursor=ft.MouseCursor.CLICK))
                            title_text = icon.get('title') or icon.get('id') or icon.get('displayIconId') or str(icon)
                            row_children.append(ft.Column([ft.Text(title_text, selectable=True), ft.Text(', '.join(icon.get('tags', [])[:5]) if icon.get('tags') else '')]))
                            row_children.append(ft.ElevatedButton('Use', on_click=use_icon))
                            results_list.controls.append(ft.Row(row_children, alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
                    self.page.update()
                except Exception as e:
                    results_list.controls.append(ft.Text(f'Search failed: {e}'))
                    self.page.update()
            threading.Thread(target=search_worker, daemon=True).start()

        def close_replace(_e=None):
            self.page.open(self.dialog)
            self.page.update()

        self.dialog = ft.AlertDialog(
            title=ft.Text('Replace icon'),
            content=ft.Column([
                ft.Row([search_field, ft.TextButton('Search', on_click=do_search)]),
                ft.Row([include_yoto, max_searches_field, top_n_field]),
                results_list
            ], width=900),
            actions=[ft.TextButton('Close', on_click=close_replace)],
        )
        self.page.open(self.dialog)
        do_search(None)
