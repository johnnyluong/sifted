Current topics:
<topics>
{% for t in topics %}- id {{ t.id }} "{{ t.name }}" ({{ t.posts }} posts): {{ t.description }}
{% else %}(none)
{% endfor %}</topics>

Kept posts, newest first:
<posts>
{{ posts_json }}
</posts>
