# Social Preview Guidance

Use the site metadata in `docs/index.html` as the source of truth for title and description.

Recommended preview image:

- Size: 1200 x 630 PNG.
- Content: RepoMind wordmark, "Local-first repository intelligence for AI coding agents", and "Index once. Understand everywhere."
- Visual style: developer-tool aesthetic, high contrast, no fake usage counts, no testimonials, no customer logos, and no unsupported savings claims.
- GitHub Pages path after adding the image: `docs/assets/social-preview.png`.

After the image exists, add:

```html
<meta property="og:image" content="https://raazlehra.github.io/Repomind/assets/social-preview.png" />
<meta name="twitter:image" content="https://raazlehra.github.io/Repomind/assets/social-preview.png" />
```
