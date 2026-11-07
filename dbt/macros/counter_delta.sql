{# PIADE counter rule (design 5.4, plan rulings R1): a negative delta is a counter reset and a
   delta above the glitch limit is impossible production; both become null. A missing delta
   (first or last row of a machine) is 'none'. #}
{% macro counter_flag(delta, limit) -%}
    case
        when {{ delta }} is null then 'none'
        when {{ delta }} < 0 then 'reset'
        when {{ delta }} > {{ limit }} then 'glitch'
        else 'ok'
    end
{%- endmacro %}

{% macro counter_delta(delta, limit) -%}
    case when {{ delta }} >= 0 and {{ delta }} <= {{ limit }} then {{ delta }} end
{%- endmacro %}
