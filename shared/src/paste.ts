/**
 * Word's lists, pasted into a block (decision D5; phase 0 report, recommendation 4). Word writes each list item as
 * a paragraph styled "mso-list:lN levelM", with its bullet or number as text inside a conditional comment or an
 * "mso-list:Ignore" span. Left alone they become paragraphs beginning with "·". Here they become real lists, nested
 * by level, numbered lists keeping their first number; the rest of the HTML is left as it is. The editor's paste
 * then keeps only what its schema allows, as for any HTML.
 */

const LIST_ITEM = /<p\b([^>]*?mso-list:\s*l(\d+)\s+level(\d+)[^>]*)>([\s\S]*?)<\/p>/gi
const CONDITIONAL = /<!(?:--)?\[if !supportLists\](?:--)?>([\s\S]*?)<!(?:--)?\[endif\](?:--)?>/i
const IGNORE_SPAN = /<span\b[^>]*mso-list:\s*Ignore[^>]*>/i
// A number or letter, Latin or Arabic, then "." or ")": a numbered item; anything else is a bullet.
const NUMBERED = /^\(?([0-9٠-٩۰-۹]+|[A-Za-zء-ي]{1,3})[.)]$/

interface Item {
  start: number
  end: number
  level: number
  tag: 'ul' | 'ol'
  first: number | null
  body: string
}

/** The text of an HTML fragment: tags removed, spaces made plain. */
function textOf(html: string): string {
  return html
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;|&#160;/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Removes the span opening at ``at`` with everything inside it, nested spans included. Returns [rest, removed]. */
function cutSpan(html: string, at: number): [string, string] {
  const tags = /<\/?span\b[^>]*>/gi
  tags.lastIndex = at
  let depth = 0
  for (let tag = tags.exec(html); tag; tag = tags.exec(html)) {
    depth += tag[0][1] === '/' ? -1 : 1
    if (depth === 0) return [html.slice(0, at) + html.slice(tags.lastIndex), html.slice(at, tags.lastIndex)]
  }
  return [html, '']
}

function itemOf(match: RegExpMatchArray): Item {
  let body = match[4]
  let marker = ''
  const conditional = CONDITIONAL.exec(body)
  if (conditional) {
    marker = textOf(conditional[1])
    body = body.replace(CONDITIONAL, '')
  }
  const ignore = IGNORE_SPAN.exec(body)
  if (ignore) {
    const [rest, removed] = cutSpan(body, ignore.index)
    marker ||= textOf(removed)
    body = rest
  }
  body = body.replace(/<!(?:--)?\[(?:if [^\]]*|endif)\](?:--)?>/gi, '').trim()
  const numbered = NUMBERED.exec(marker)
  const digits = numbered && /^[0-9]+$/.test(numbered[1]) ? Number(numbered[1]) : null
  return {
    start: match.index!,
    end: match.index! + match[0].length,
    level: Number(match[3]),
    tag: numbered ? 'ol' : 'ul',
    first: digits,
    body,
  }
}

function listOf(items: Item[]): string {
  let out = ''
  const open: Array<{ level: number; tag: string }> = []
  const opening = (item: Item) =>
    item.tag === 'ol' && item.first !== null && item.first !== 1 ? `<ol start="${item.first}">` : `<${item.tag}>`
  for (const item of items) {
    while (open.length && open[open.length - 1].level > item.level) out += `</li></${open.pop()!.tag}>`
    const top = open[open.length - 1]
    if (top && top.level === item.level && top.tag === item.tag) {
      out += '</li>'
    } else {
      if (top && top.level === item.level) out += `</li></${open.pop()!.tag}>` // the same level, another kind of list
      out += opening(item)
      open.push({ level: item.level, tag: item.tag })
    }
    out += `<li><p>${item.body}</p>`
  }
  while (open.length) out += `</li></${open.pop()!.tag}>`
  return out
}

export function wordLists(html: string): string {
  if (!/mso-list/i.test(html)) return html
  const items = [...html.matchAll(LIST_ITEM)].map(itemOf)
  if (!items.length) return html
  let out = ''
  let at = 0
  let group: Item[] = []
  const flush = () => {
    if (group.length) out += listOf(group)
    group = []
  }
  for (const item of items) {
    const between = html.slice(at, item.start)
    if (group.length && between.trim() !== '') flush()
    if (!group.length) out += between // what stands before the list stays; blank space between items does not
    group.push(item)
    at = item.end
  }
  flush()
  return out + html.slice(at)
}
