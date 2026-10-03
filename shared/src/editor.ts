import { type Extensions, getSchema } from '@tiptap/core'
import Link from '@tiptap/extension-link'
import StarterKit from '@tiptap/starter-kit'

/** The links the server accepts (decision D27): http, https and mailto, at most 2000 characters. */
export function isSafeHref(href: string | null | undefined): boolean {
  if (typeof href !== 'string' || href.length > 2000) return false
  return /^(https?:\/\/|mailto:)/i.test(href.trim())
}

/**
 * Links as the server validates them. A pasted link keeps only its href, and only a safe one; target,
 * rel, class and title always take the editor's values, so nothing pasted from another page can make
 * the document unsavable (review finding: pasted links blocked every save).
 */
const SafeLink = Link.extend({
  addAttributes() {
    return {
      href: { default: null, parseHTML: (element) => element.getAttribute('href') },
      target: { default: '_blank', parseHTML: () => null },
      rel: { default: 'noopener noreferrer nofollow', parseHTML: () => null },
      class: { default: null, parseHTML: () => null },
      title: { default: null, parseHTML: () => null },
    }
  },
}).configure({
  autolink: false,
  openOnClick: false,
  linkOnPaste: false,
  isAllowedUri: (url: string) => isSafeHref(url),
})

/**
 * The single definition of the block editor's schema. The web client and the
 * collaboration service both build from it, so content converts identically
 * on both sides. Undo is handled by Yjs, and links are never created
 * automatically (decision D5).
 */
export function editorExtensions(): Extensions {
  return [StarterKit.configure({ undoRedo: false, link: false }), SafeLink]
}

export const editorSchema = getSchema(editorExtensions())
