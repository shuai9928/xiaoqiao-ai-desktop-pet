"""Retheme an open chat without reopening it or changing its conversation.

Called when AI pet mode switches character/theme while the chat is open: the
draft, history, scroll position and focus stay; only colours and images change.
"""
from PIL import ImageTk


def retheme_chat(chat, palette, theme_key):
    if getattr(chat, '_theme_key', None) == theme_key:
        return
    if not chat.win.winfo_exists():
        return
    previous = chat.A
    color_names = ('BG', 'ELEV', 'ELEV2', 'ELEV3', 'TEXT', 'TEXT2', 'TEXT3', 'BLUE')
    remap = {previous.hexc(getattr(previous, name)).lower():
             palette.hexc(getattr(palette, name)) for name in color_names}
    chat.A, chat._theme_key, chat._bg = palette, theme_key, palette.BG

    def recolor(widget):
        for option in ('background', 'foreground', 'activebackground', 'activeforeground',
                       'insertbackground', 'disabledforeground', 'troughcolor'):
            try:
                color = str(widget.cget(option)).lower()
                if color in remap:
                    widget.configure(**{option: remap[color]})
            except Exception:
                pass  # Not all Tk widget classes expose the same color options.
        for child in widget.winfo_children():
            recolor(child)

    recolor(chat.win)
    chat.log.tag_configure('hint', foreground=palette.hexc(palette.TEXT2))
    chat.log.tag_configure('stamp', foreground=palette.hexc(palette.TEXT3))
    chat._bg_photo = ImageTk.PhotoImage(type(chat).cached_bg(chat.w_, chat.h_, chat._tail, palette),
                                        master=chat.win)
    chat.cv.itemconfigure(chat._bg_item, image=chat._bg_photo)
    chat._field_img = ImageTk.PhotoImage(palette.pill(chat._field_width, int(36 * chat.u)),
                                         master=chat.win)
    chat._field_label.configure(image=chat._field_img)
    # Replace references instead of retaining a full old image set per switch.
    chat._imgs = []
    for button, size, glyph, accented in chat._control_specs:
        images = {state: ImageTk.PhotoImage(palette.circle_button(
            size, glyph, state, palette.BLUE if accented else None), master=chat.win)
                  for state in ('normal', 'hover', 'pressed', 'disabled')}
        button._imgs.clear()
        button._imgs.update(images)  # _wire callbacks hold this same dict.
        chat._imgs.append(button._imgs)
        button.configure(image=images['disabled' if str(button['state']) == 'disabled' else 'normal'])
    view = chat.log.yview()
    current = set(chat.log.image_names())
    chat.log.configure(state='normal')
    try:
        for name, (role, text, count) in list(chat._message_images.items()):
            if name not in current:
                del chat._message_images[name]
                continue
            photo = chat._bubble(role, text, count)
            chat.log.image_configure(name, image=photo)
            last = chat._last_msg
            if last and last[4] == name:
                chat._last_msg = last[:5] + (photo,)
        if chat._typing is not None:
            chat._typing_img = ImageTk.PhotoImage(
                palette.typing_bubble(chat._pf, 0, palette.BG), master=chat.win)
            chat.log.image_configure(chat._typing_name, image=chat._typing_img)
    finally:
        chat.log.configure(state='disabled')
        if view:
            chat.log.yview_moveto(view[0])
