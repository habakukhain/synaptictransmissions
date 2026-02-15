# Synaptic Transmissions

Personal blog at [synaptictransmissions.com](https://synaptictransmissions.com) - "Central Latency Reduction"

## Local Development

```bash
bundle install
bundle exec jekyll serve
```

Site will be available at http://localhost:4000

## Structure

- `_posts/` - Published blog posts (format: `YYYY-MM-DD-title.md`)
- `_drafts/` - Work-in-progress posts
- `menu/` - Static pages (About, Contact, Writing, Open Questions)
- `assets/img/` - Post images
- `_data/settings.yml` - Site configuration (menu, social links)

## Writing Posts

Create a new file in `_posts/` with this front matter:

```yaml
---
layout: post
title: "Your Post Title"
author: "Habakuk Hain"
categories: [category]
tags: [tag1, tag2]
image: mountains.jpg
---
```

## Features

- Giscus comments (GitHub-based)
- MathJax for LaTeX equations
- RSS feed at `/feed.xml`
- Syntax highlighting

## Theme

Based on [Lagrange](https://github.com/LeNPaul/Lagrange) by Paul Le, licensed under MIT.
