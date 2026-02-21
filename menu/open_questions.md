---
layout: page
title: Open Questions
permalink: /questions/
comments: true
---

These are questions that arise from the literature that I find particularly interesting and worth tracking. You can comment on each question if you find interesting puzzle pieces. If you come across an interesting question yourself and want to convince me to include it, [send me an e-mail](mailto:habakuk@e-hain.de).

{% for question in site.questions %}
- [{{ question.title }}]({{ question.url | relative_url }})
{% endfor %}
