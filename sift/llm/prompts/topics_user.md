<topics>
{% for t in topics %}- id {{ t.id }} "{{ t.name }}" ({{ t.posts }} posts): {{ t.description }}
{% else %}(none yet)
{% endfor %}</topics>
{% if posts %}
<posts>
{{ posts_json }}
</posts>
{% endif %}
