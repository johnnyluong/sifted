<topic>{{ topic }}{% if topic_description %} ({{ topic_description }}){% endif %}</topic>

{% if previous_points %}<previous_points>
{% for p in previous_points %}- {{ p }}
{% endfor %}</previous_points>

{% endif %}<sources>
{{ sources_json }}
</sources>
