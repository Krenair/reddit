# The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
#
# The Original Code is Reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
#
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.models import *
from filters import unsafe, websafe
from r2.lib.utils import vote_hash, UrlParser, timesince

from r2.lib.media import s3_direct_url

from mako.filters import url_escape
import simplejson
import os.path
from copy import copy
import random
from pylons import g, c
from pylons.i18n import _, ungettext

def static(path):
    """
    Simple static file maintainer which automatically paths and
    versions files being served out of static.

    In the case of JS and CSS where g.uncompressedJS is set, the
    version of the file is set to be random to prevent caching and it
    mangles the path to point to the uncompressed versions.
    """
    
    dirname, fname = os.path.split(path)
    fname = fname.split('?')[0]
    query = ""

    # if uncompressed, randomize a url query to bust caches
    if g.uncompressedJS:
        query = "?v=" + str(random.random()).split(".")[-1]
    else:
        if fname in g.static_names:
            fname = g.static_names[fname]
            path = os.path.join(dirname, fname)

    # don't mangle paths
    if dirname:
        return path + query

    if g.uncompressedJS:
        extension = path.split(".")[1:]
        if extension and extension[-1] in ("js", "css"):
            return os.path.join(c.site.static_path, extension[-1], path) + query

    return os.path.join(c.site.static_path, path) + query

def s3_https_if_secure(url):
    # In the event that more media sources (other than s3) are added, this function should be corrected
    if not c.secure:
        return url
    replace = "https://"
    if not url.startswith("http://%s" % s3_direct_url):
         replace = "https://%s/" % s3_direct_url
    return url.replace("http://", replace)

def generateurl(context, path, **kw):
    if kw:
        return path + '?' + '&'.join(["%s=%s"%(k, url_escape(v)) \
                                      for k, v in kw.iteritems() if v])
    return path

def class_dict():
    t_cls = [Link, Comment, Message, Subreddit]
    l_cls = [Listing, OrganicListing]

    classes  = [('%s: %s') % ('t'+ str(cl._type_id), cl.__name__ ) for cl in t_cls] \
             + [('%s: %s') % (cl.__name__, cl._js_cls) for cl in l_cls]

    res = ', '.join(classes)
    return unsafe('{ %s }' % res)

def calc_time_period(comment_time):
    # Set in front.py:GET_comments()
    previous_visits = c.previous_visits

    if not previous_visits:
        return ""

    rv = ""
    for i, visit in enumerate(previous_visits):
        if comment_time > visit:
            rv = "comment-period-%d" % i

    return rv

def replace_render(listing, item, render_func):
    def _replace_render(style = None, display = True):
        """
        A helper function for listings to set uncachable attributes on a
        rendered thing (item) to its proper display values for the current
        context.
        """
        style = style or c.render_style or 'html'
        replacements = {}

        child_txt = ( hasattr(item, "child") and item.child )\
            and item.child.render(style = style) or ""
        replacements["childlisting"] = child_txt


        #only LinkListing has a show_nums attribute
        if listing:
            if hasattr(listing, "show_nums"):
                if listing.show_nums:
                    num_str = str(item.num)
                    if hasattr(listing, "num_margin"):
                        num_margin = str(listing.num_margin)
                    else:
                        num_margin = "%.2fex" % (len(str(listing.max_num))*1.1)
                else:
                    num_str = ''
                    num_margin = "0px;display:none"

                replacements["numcolmargin"] = num_margin
                replacements["num"] = num_str

            if hasattr(listing, "max_score"):
                mid_margin = len(str(listing.max_score))
                if hasattr(listing, "mid_margin"):
                    mid_margin = str(listing.mid_margin)
                elif mid_margin == 1:
                    mid_margin = "15px"
                else:
                    mid_margin = "%dex" % (mid_margin+1)

                replacements["midcolmargin"] = mid_margin

            #$votehash is only present when voting arrows are present
            if c.user_is_loggedin:
                replacements['votehash'] = vote_hash(c.user, item,
                                                     listing.vote_hash_type)
        if hasattr(item, "num_comments"):
            if not item.num_comments:
                # generates "comment" the imperative verb
                com_label = _("comment {verb}")
                com_cls = 'comments empty'
            else:
                # generates "XX comments" as a noun
                com_label = ungettext("comment", "comments", item.num_comments)
                com_label = strings.number_label % dict(num=item.num_comments,
                                                        thing=com_label)
                com_cls = 'comments'
            if style == "compact":
                com_label = unicode(item.num_comments)
            replacements['numcomments'] = com_label
            replacements['commentcls'] = com_cls

        replacements['display'] =  "" if display else "style='display:none'"

        if hasattr(item, "render_score"):
            # replace the score stub
            (replacements['scoredislikes'],
             replacements['scoreunvoted'],
             replacements['scorelikes'])  = item.render_score

        # compute the timesince here so we don't end up caching it
        if hasattr(item, "_date"):
            if hasattr(item, "promoted") and item.promoted is not None:
                from r2.lib import promote
                # promoted links are special in their date handling
                replacements['timesince'] = timesince(item._date -
                                                      promote.timezone_offset)
            else:
                replacements['timesince'] = timesince(item._date)

            replacements['time_period'] = calc_time_period(item._date)

        # Set in front.py:GET_comments()
        replacements['previous_visits_hex'] = c.previous_visits_hex

        renderer = render_func or item.render
        res = renderer(style = style, **replacements)

        if isinstance(res, (str, unicode)):
            rv = unsafe(res)
            if g.debug:
                for leftover in re.findall('<\$>(.+?)(?:<|$)', rv):
                    print "replace_render didn't replace %s" % leftover

            return rv

        return res

    return _replace_render

def get_domain(cname = False, subreddit = True, no_www = False):
    """
    returns the domain on the current subreddit, possibly including
    the subreddit part of the path, suitable for insertion after an
    "http://" and before a fullpath (i.e., something including the
    first '/') in a template.  The domain is updated to include the
    current port (request.port).  The effect of the arguments is:

     * no_www: if the domain ends up being g.domain, the default
       behavior is to prepend "www." to the front of it (for akamai).
       This flag will optionally disable it.

     * cname: whether to respect the value of c.cname and return
       c.site.domain rather than g.domain as the host name.

     * subreddit: if a cname is not used in the resulting path, flags
       whether or not to append to the domain the subreddit path (sans
       the trailing path).

    """
    # locally cache these lookups as this gets run in a loop in add_props
    domain = g.domain
    domain_prefix = c.domain_prefix
    site  = c.site
    ccname = c.cname
    if not no_www and domain_prefix:
        domain = domain_prefix + "." + domain
    if cname and ccname and site.domain:
        domain = site.domain
    if hasattr(request, "port") and request.port:
        domain += ":" + str(request.port)
    if (not ccname or not cname) and subreddit:
        domain += site.path.rstrip('/')
    return domain

def dockletStr(context, type, browser):
    domain      = get_domain()

    # while site_domain will hold the (possibly) cnamed version
    site_domain = get_domain(True)

    if type == "serendipity!":
        return "http://"+site_domain+"/random"
    elif type == "submit":
        return ("javascript:location.href='http://"+site_domain+
               "/submit?url='+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title)")
    elif type == "reddit toolbar":
        return ("javascript:%20var%20h%20=%20window.location.href;%20h%20=%20'http://" +
                site_domain + "/s/'%20+%20escape(h);%20window.location%20=%20h;")
    else:
        # these are the linked/disliked buttons, which we have removed
        # from the UI
        return (("javascript:function b(){var u=encodeURIComponent(location.href);"
                 "var i=document.getElementById('redstat')||document.createElement('a');"
                 "var s=i.style;s.position='%(position)s';s.top='0';s.left='0';"
                 "s.zIndex='10002';i.id='redstat';"
                 "i.href='http://%(site_domain)s/submit?url='+u+'&title='+"
                 "encodeURIComponent(document.title);"
                 "var q=i.firstChild||document.createElement('img');"
                 "q.src='http://%(domain)s/d/%(type)s.png?v='+Math.random()+'&uh=%(modhash)s&u='+u;"
                 "i.appendChild(q);document.body.appendChild(i)};b()") %
                dict(position = "absolute" if browser == "ie" else "fixed",
                     domain = domain, site_domain = site_domain, type = type,
                     modhash = c.modhash if c.user else ''))



def add_sr(path, sr_path = True, nocname=False, force_hostname = False, retain_extension=True):
    """
    Given a path (which may be a full-fledged url or a relative path),
    parses the path and updates it to include the subreddit path
    according to the rules set by its arguments:

     * force_hostname: if True, force the url's hotname to be updated
       even if it is already set in the path, and subject to the
       c.cname/nocname combination.  If false, the path will still
       have its domain updated if no hostname is specified in the url.
    
     * nocname: when updating the hostname, overrides the value of
       c.cname to set the hotname to g.domain.  The default behavior
       is to set the hostname consistent with c.cname.

     * sr_path: if a cname is not used for the domain, updates the
       path to include c.site.path.

    For caching purposes: note that this function uses:
      c.cname, c.render_style, c.site.name
    """
    # don't do anything if it is just an anchor
    if path.startswith('#') or path.startswith('javascript:'):
        return path

    u = UrlParser(path)
    if sr_path and (nocname or not c.cname):
        u.path_add_subreddit(c.site)

    if not u.hostname or force_hostname:
        u.hostname = get_domain(cname = (c.cname and not nocname),
                                subreddit = False)

    if retain_extension:
        if c.render_style == 'mobile':
            u.set_extension('mobile')

        elif c.render_style == 'compact':
            u.set_extension('compact')

    return u.unparse()

def join_urls(*urls):
    """joins a series of urls together without doubles slashes"""
    if not urls:
        return
    
    url = urls[0]
    for u in urls[1:]:
        if not url.endswith('/'):
            url += '/'
        while u.startswith('/'):
            u = utils.lstrips(u, '/')
        url += u
    return url

def style_line(button_width = None, bgcolor = "", bordercolor = ""):
    style_line = ''
    bordercolor = c.bordercolor or bordercolor
    bgcolor     = c.bgcolor or bgcolor
    if bgcolor:
        style_line += "background-color: #%s;" % bgcolor
    if bordercolor:
        style_line += "border: 1px solid #%s;" % bordercolor
    if button_width:
        style_line += "width: %spx;" % button_width
    return style_line

def choose_width(link, width):
    if width:
        return width - 5
    else:
        if hasattr(link, "_ups"):
            return 100 + (10 * (len(str(link._ups - link._downs))))
        else:
            return 110

def panel_size(state):
    "the frame.cols of the reddit-toolbar's inner frame"
    return '400px, 100%' if state =='expanded' else '0px, 100%x'

# Appends to the list "attrs" a tuple of:
# <priority (higher trumps lower), letter,
#  css class, i18n'ed mouseover label, hyperlink (opt), img (opt)>
def add_attr(attrs, kind, label=None, link=None, cssclass=None, symbol=None):
    from r2.lib.template_helpers import static

    img = None
    symbol = symbol or kind

    if kind == 'F':
        priority = 1
        cssclass = 'friend'
        if not label:
            label = _('friend')
        if not link:
            link = '/prefs/friends'
    elif kind == 'S':
        priority = 2
        cssclass = 'submitter'
        if not label:
            label = _('submitter')
        if not link:
            raise ValueError ("Need a link")
    elif kind == 'M':
        priority = 3
        cssclass = 'moderator'
        if not label:
            raise ValueError ("Need a label")
        if not link:
            raise ValueError ("Need a link")
    elif kind == 'A':
        priority = 4
        cssclass = 'admin'
        if not label:
            label = _('reddit admin, speaking officially')
        if not link:
            link = '/help/faq#Whorunsreddit'
    elif kind in ('X', '@'):
        priority = 5
        cssclass = 'gray'
        if not label:
            raise ValueError ("Need a label")
    elif kind == 'V':
        priority = 6
        cssclass = 'green'
        if not label:
            raise ValueError ("Need a label")
    elif kind == 'B':
        priority = 7
        cssclass = 'wrong'
        if not label:
            raise ValueError ("Need a label")
    elif kind == 'special':
        priority = 98
    elif kind.startswith ('trophy:'):
        img = (kind[7:], '!', 11, 8)
        priority = 99
        cssclass = 'recent-trophywinner'
        if not label:
            raise ValueError ("Need a label")
        if not link:
            raise ValueError ("Need a link")
    else:
        raise ValueError ("Got weird kind [%s]" % kind)

    attrs.append( (priority, symbol, cssclass, label, link, img) )
