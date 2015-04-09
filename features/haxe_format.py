import re
import sublime
import sublime_plugin

try:  # Python 3
    from .haxe_helper import cache
except (ValueError):  # Python 2
    from haxe_helper import cache

header = '''
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>name</key>
    <string>Globals</string>
    <key>scope</key>
    <string>source.haxe.2</string>
    <key>settings</key>
    <dict>
        <key>shellVariables</key>
        <array>'''

shell_var_template = '''
            <dict>
                <key>name</key>
                <string>{0}</string>
                <key>value</key>
                <string><![CDATA[{1}]]></string>
            </dict>'''

footer = '''
        </array>
    </dict>
    <key>uuid</key>
    <string>0ef292cd-943a-4fb0-b43d-65959c5e6b06</string>
</dict>
</plist>'''

re_format_op_par = re.compile(r'\s*\(\s*')
re_format_cl_par = re.compile(r'\s*\)')
re_format_empty_par = re.compile(r'\(\s+\)')
re_format_colon = re.compile(r'\s*:\s*')
re_format_op_ang = re.compile(r'\s*<\s*')
re_format_cl_ang = re.compile(r'([^-\s])\s*>')
re_format_comma = re.compile(r'\s*,\s*')
re_format_assign = re.compile(r'\s*=\s*')
re_format_type_sep = re.compile(r'\s*->\s*')
re_format_semicolon = re.compile(r'\s*;')
re_format_par_c = re.compile(r'\)\s*:')

re_whitespace_style = re.compile(
    'function f(\s*)\((\s*)'
    'a(\s*):(\s*)T(\s*)<(\s*)T(\s*)>(\s*),(\s*)'
    'b\s*:\s*T(\s*)=(\s*)null(\s*)'
    '\)(\s*):\s*T(\s*)->(\s*)T(\s*);')
re_whitespace_style2 = re.compile(
    'for(\s*)\(\s*i\s+in\s0(\s*)\.\.\.(\s*)5\)')
re_brace_style = re.compile('\}([\s\n]*)else([\s\n]*)\{')

style_map = None


def format_statement(view, value):
    global style_map

    sm = style_map

    value = re_format_op_par.sub(
        '%s(%s' % (sm['HX_W_ORB'], sm['HX_ORB_W']), value)
    value = re_format_cl_par.sub('%s)' % sm['HX_W_CRB'], value)
    value = re_format_empty_par.sub('()', value)
    value = re_format_colon.sub(
        '%s:%s' % (sm['HX_W_C'], sm['HX_C_W']), value)
    value = re_format_op_ang.sub(
        '%s<%s' % (sm['HX_W_OAB'], sm['HX_OAB_W']), value)
    value = re_format_cl_ang.sub('\\1%s>' % sm['HX_W_CAB'], value)
    value = re_format_comma.sub(
        '%s,%s' % (sm['HX_W_CM'], sm['HX_CM_W']), value)
    value = re_format_assign.sub(
        '%s=%s' % (sm['HX_W_A'], sm['HX_A_W']), value)
    value = re_format_type_sep.sub(
        '%s->%s' % (sm['HX_W_AR'], sm['HX_AR_W']), value)
    value = re_format_semicolon.sub('%s;' % sm['HX_W_SC'], value)
    value = re_format_par_c.sub(')%s:' % sm['HX_CRB_W_C'], value)

    return value


class HaxeFormat(sublime_plugin.EventListener):

    def __init__(self):
        self.inited = False
        self.changed = False

    def init(self, view):
        if view.score_selector(0, 'source.haxe.2') == 0:
            return

        self.inited = True

        view.settings().add_on_change(
            'haxe_whitespace_style',
            lambda: self.update_whitespace_style(view))
        view.settings().add_on_change(
            'haxe_whitespace_style2',
            lambda: self.update_whitespace_style2(view))
        view.settings().add_on_change(
            'haxe_brace_style',
            lambda: self.update_brace_style(view))

        self.update_whitespace_style(view)
        self.update_whitespace_style2(view)
        self.update_brace_style(view)

    def mark(self):
        if self.changed:
            return

        self.changed = True

        sublime.set_timeout(lambda: self.save_shell_variables(), 100)

    def on_activated(self, view):
        if not self.inited:
            self.init(view)

    def on_load(self, view):
        if not self.inited:
            self.init(view)

    def save_shell_variables(self):
        global style_map

        self.changed = False
        s = header

        for key in style_map.keys():
            s += shell_var_template.format(key, style_map[key])

        s += footer

        svars = cache('Haxe.ShellVars.tmPreferences')
        if s != svars:
            cache('Haxe.ShellVars.tmPreferences', s)

    def update_brace_style(self, view):
        global style_map

        def_style = '} else {'
        style = view.settings().get('haxe_brace_style')

        if 'brace_style' not in style_map or style_map['brace_style'] != style:
            style_map['brace_style'] = style

            mo = re_brace_style.search(style)
            if mo is None:
                mo = re_brace_style.search(def_style)

            style_map['HX_CCB_W'] = mo.group(1)  # }_
            style_map['HX_W_OCB'] = mo.group(2)  # _{

            self.mark()

    def update_whitespace_style(self, view):
        global style_map

        def_style = 'function f(a:T<T>, b:T = null):T->T;'
        style = view.settings().get('haxe_whitespace_style', def_style)

        if style_map is None:
            style_map = {}

        if 'style' not in style_map or style_map['style'] != style:
            style_map['style'] = style

            mo = re_whitespace_style.search(style)
            if mo is None:
                mo = re_whitespace_style.search(def_style)

            style_map['HX_W_ORB'] = mo.group(1)  # _(
            style_map['HX_ORB_W'] = mo.group(2)  # (_
            style_map['HX_W_C'] = mo.group(3)  # _:
            style_map['HX_C_W'] = mo.group(4)  # :_
            style_map['HX_W_OAB'] = mo.group(5)  # _<
            style_map['HX_OAB_W'] = mo.group(6)  # <_
            style_map['HX_W_CAB'] = mo.group(7)  # _>
            style_map['HX_W_CM'] = mo.group(8)  # _,
            style_map['HX_CM_W'] = mo.group(9)  # ,_
            style_map['HX_W_A'] = mo.group(10)  # _=
            style_map['HX_A_W'] = mo.group(11)  # =_
            style_map['HX_W_CRB'] = mo.group(12)  # _)
            style_map['HX_CRB_W_C'] = mo.group(13)  # ):
            style_map['HX_W_AR'] = mo.group(14)  # _->
            style_map['HX_AR_W'] = mo.group(15)  # ->_
            style_map['HX_W_SC'] = mo.group(16)  # _;

            self.mark()

    def update_whitespace_style2(self, view):
        global style_map

        def_style = 'for (i in 0 ... 5)'
        style = view.settings().get('haxe_whitespace_style2')

        if 'style2' not in style_map or style_map['style2'] != style:
            style_map['style2'] = style

            mo = re_whitespace_style2.search(style)
            if mo is None:
                mo = re_whitespace_style2.search(def_style)

            style_map['HX_K_W_ORB'] = mo.group(1)  # for_(
            style_map['HX_W_TD'] = mo.group(2)  # _...
            style_map['HX_TD_W'] = mo.group(3)  # ..._

            self.mark()
