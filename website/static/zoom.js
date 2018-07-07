/**
 * Zoom is responsible for zooming and panning of canvas and keeping it in borders of specified viewport.
 *
 * Following terms are used in this module:
 * - canvas: an html element (presumably <svg>) to be zoomed and moved
 * - viewport: a container restricting movement and scale of the canvas
 */
var Zoom = function()
{
    var svg;
    var min;
    var max;
    var config;
    var zoom;
    var viewport;

    var viewport_size = [],
        canvas_size = [];

    function callback()
    {
        transform(d3.event.translate, d3.event.scale, 0);
        config.on_move(this)
    }

    function transform(translate, scale, animation_speed)
    {
        // canvas_size[0] * scale represents real width of an svg element after scaling
        translate[0] = Math.min(0, Math.max(viewport_size[0] - canvas_size[0] * scale, translate[0]));
        translate[1] = Math.min(0, Math.max(viewport_size[1] - canvas_size[1] * scale, translate[1]));

        zoom.translate(translate);
        zoom.scale(scale);

        if(animation_speed)
        {
            svg.transition()
                .duration(animation_speed)
                .attr('transform', 'translate(' + translate + ')scale(' + scale + ')');
        }
        else
        {
            svg
                .attr('transform', 'translate(' + translate + ')scale(' + scale + ')');
        }
    }

    function set_viewport_size(width, height)
    {
        viewport_size[0] = width;
        viewport_size[1] = height;
        canvas_size[0] = Math.max(viewport_size[0] * config.max, viewport_size[0] / config.min);
        canvas_size[1] = Math.max(viewport_size[1] * config.max, viewport_size[1] / config.min);

        svg.attr('viewBox', '0 0 ' + canvas_size[0] + ' ' + canvas_size[1]);
        svg.attr('width', canvas_size[0] + 'px');
        svg.attr('height', canvas_size[1] + 'px');
        svg.style('transform-origin', 'top left');
    }

    function viewport_to_canvas(position)
    {
        return [
            position[0] / viewport_size[0] * canvas_size[0],
            position[1] / viewport_size[1] * canvas_size[1]
        ]
    }

    function canvas_to_viewport(position)
    {
        return [
            position[0] * viewport_size[0] / canvas_size[0],
            position[1] * viewport_size[1] / canvas_size[1]
        ]
    }

    /**
     * Configuration object for Zoom.
     * @typedef {Object} Config
     * @property {number} min - 1 / how many times the element can be zoomed-out?
     * e.g. 1/5 means that when maximally zoomed out, the content will be of 1/5 its original size
     * @property {max} max - how many times the element can be zoomed-in?
     * e.g. 2 means that when maximally zoomed in, the content will be twice its original size
     * @property {function} on_move - callback called after each zoom/move transformation
     * @property {D3jsElement} element - the element to be zoomed and panned (canvas)
     * @property {HTMLElement} viewport - element defining boundaries of the transformed element
     */
    return {
        /**
         * Initialize Zoom.
         * @param {Config} user_config
         */
        init: function(user_config)
        {
            config = user_config;
            svg = config.element;
            min = config.min;
            max = config.max;

            zoom = prepareZoom(min, max, callback);

            viewport = d3.select(config.viewport);
            viewport.call(zoom)
        },
        viewport_to_canvas: viewport_to_canvas,
        canvas_to_viewport: canvas_to_viewport,
        set_viewport_size: set_viewport_size,
        set_zoom: function(new_scale)
        {
            var old_scale = zoom.scale();

            // trim the new_scale to pre-set limit (min & max)
            zoom.scale(new_scale);
            new_scale = zoom.scale();

            // keep the focus in the same place as it was before zooming
            var translate = zoom.translate();
            var factor = old_scale - new_scale;
            translate = [
                translate[0] + factor * canvas_size[0] / 2,
                translate[1] + factor * canvas_size[1] / 2
            ];

            // apply the new zoom
            transform(translate, new_scale, 600)
        },
        center_on: function(position, radius, animation_speed)
        {
            animation_speed = (typeof animation_speed === 'undefined') ? 750: animation_speed;

            var scale = Math.min(viewport_size[0], viewport_size[1]) / radius;

            position[0] *= -scale;
            position[1] *= -scale;
            position[0] += viewport_size[0] / 2;
            position[1] += viewport_size[1] / 2;

            transform(position, scale, animation_speed)
        },
        get_zoom: function(){
            return zoom.scale();
        }
    }
}

