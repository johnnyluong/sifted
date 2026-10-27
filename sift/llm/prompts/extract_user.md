Source: {{ source }}
{% if notes %}Notes: {{ notes | join(" ") }}
{% endif %}
<author>{{ author_handle or "unknown" }}</author>

<caption>
{{ caption or post_text or "(none)" }}
</caption>

<transcript>
{{ transcript or "(no speech)" }}
</transcript>

{{ frame_count }} image(s) from the post are attached above, in order: frames from its video, then its slides.
