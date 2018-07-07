var NeedlePlot = function ()
{
    var svg, zoom, vis, vertical_scalable, unit
    var scale = 1
	var position = 0
    var dispatch = d3.dispatch('zoomAndMove')

    var paddings, needles, sites, site_boxes;

    var legend = {
        x:
        {
            obj: null
        },
        y:
        {
            obj: null
        }
    }

    var Axis = function()
    {
        this.scale = null
        this.group = null
        this.obj = null

        this.createObj = function(orient)
        {
            this.obj = d3.svg.axis()
                .orient(orient)
                .scale(this.scale)
        }

        this.createGroup = function(class_name)
        {
            this.group = paddings.append('g')
               .attr('class', 'axis ' + class_name)
               .call(this.obj)
        }

        this.setDomain = function(start, end)
        {
            this.start = start
            this.end = end
            this.scale.domain([start, end])
        }

        this.getCoverage = function()
        {
            return this.end / scale
        }

        this.moveTo = function(start_pos)
        {
            this.scale.domain([start_pos, start_pos + this.getCoverage()])
        }

        this.getShiftLimit = function()
        {
            return this.getCoverage() - this.end
        }
    }

    var axes = {
        x: new Axis(),
        y: new Axis()
    }

    var config = {
        use_log: false, // should logarithmic (base 10) scale by used instead of linear?
        site_height: 10,
        animations_speed: 200,
        // 90 is width of description
        paddings: {bottom: 40, top: 30, left: 89, right: 1},
        y_scale: 'auto',
        sequenceLength: null,
        element: null,
        data: {
            mutations: null,
            sites: null
        },
        legends: {x: 'Sequence', y: '# of mutations'},
        width: 600,
        height: null,
        zoom_callback: null,
        position_callback: null,
        ratio: 0.5,
        min_zoom: 1,
        max_zoom: 10,
        // colors of sites are determined by their's css class
        mutations_color_map: {
            // mutation_category: color
        },
        // templates for tooltips
        needle_tooltip: null,
        site_tooltip: null,
    }

    function _adjustPlotDimensions()
    {
        if(!config.width && !config.height)
        {
            config.width = config.sequenceLength
        }

        if(config.height && config.width)
        {
            config.ratio = config.height / config.width
        }
        else if(!config.height)
        {
            config.height = config.width * config.ratio
        }
        else if(!config.width)
        {
            config.height = config.width * config.ratio
        }
    }

    function configure(new_config)
    {
        // Automatic configuration update:
        update_object(config, new_config)

        get_remote_if_needed(config, 'data')

        // Manual configuration patching:
        _adjustPlotDimensions()

    }

    function is_color_dark(color)
    {
        var rgb = d3.rgb(color)
        var yiq = ((rgb.r * 299) + (rgb.g * 587) + (rgb.b * 114)) / 1000
	    return yiq < 128
    }

    function scaleToNeedles()
    {
		if (config.y_scale === 'auto')
		{
            var accessor = function(mutation) {
                return mutation.value
            }
			config.y_scale_max = d3.max(config.data.mutations, accessor)
			config.y_scale_min = d3.min(config.data.mutations, accessor)
		}
    }

    function _rescalePlot()
    {
        svg
            .attr('viewBox', '0 0 ' + config.width + ' ' + config.height)

		unit = (config.width - config.paddings.left - config.paddings.right) / config.sequenceLength

        axes.x.scale
            .range([0, config.width - config.paddings.left - config.paddings.right])

        axes.y.scale
            .range([config.height - config.paddings.top - config.site_height, config.paddings.bottom])

        axes.y.obj.scale(axes.y.scale)
        axes.y.group.call(axes.y.obj)

		var bottom_axis_pos = config.height - config.paddings.bottom

        axes.x.obj
            .scale(axes.x.scale)
            .tickSize(config.site_height + 3)

        axes.x.group
	        .attr('transform', 'translate(' + [0, bottom_axis_pos] + ')')
            .call(axes.x.obj)

        sites
            .attr('transform', function(d)
                {
                    return 'translate(' + [posToX(d.start), bottom_axis_pos] + ')'
                }
            )

        site_boxes
			.attr('width', function(d){ return posToX(d.end - d.start) })

        needles
            .attr('transform', function(d)
                {
                    return 'translate(' + [posToX(d.pos), 0] + ')'
                }
            )

        needles.selectAll('line')
            .attr('stroke-width', posToX(1) / 2 + 'px')
            .attr('y1', function(d){ return axes.y.scale(d.value) + 'px' })
            .attr('y2', bottom_axis_pos + 'px')

        leftPadding.attr('height', config.height)

        if(legend.x.obj)
            legend.x.obj.attr('x', config.width / 2)
        if(legend.y.obj)
            legend.y.obj.attr('transform','translate(' + -(config.paddings.left - 15) + ' ' + config.height / 2 + ') rotate(-90)')

        adjustContent()
    }

    function append_group(selection, class_name)
    {
        selection
            .append('g')
            .attr('class', class_name)
    }

    function create_needles(vis, needle_tooltip)
    {
        var needles = vis.selectAll('.needle')
            .data(
                config.data.mutations
                    .sort(function(a,b){ return b.value - a.value })
            )
            .enter()
            .append('g')
            .attr('class', 'needle')
            .call(needle_tooltip.bind)

        needles
            .append('line')
                .attr('x1', 0)
                .attr('x2', 0)


        // numerate needles
        var i = 0
        needles.
            each(function(mutation){ mutation.id = i++ })

        // lets group needle heads occurring in the same place
        var head_groups = {}

        needles.
            each(function(mutation){

                var key = mutation.pos + ':' + mutation.value
                if(key in head_groups)
                {
                    head_groups[key].push(mutation.id)
                }
                else
                {
                    head_groups[key] = [mutation.id]
                }
            })

        // add a head of a needle
        var head = needles
            .append('g')
            .attr('class', 'head')
            .attr('id', function(d){ return 'h_' + d.id })

        head.append('circle')
            .attr('fill', function(d)
                {
                    return config.mutations_color_map[d.category]
                }
            )

        // add count of overlaying heads to those
        // which are overlaid / overlaying

        function is_overlaying(d)
        {
            var key = d.pos + ':' + d.value
            var head_group = head_groups[key]
            return head_group.length > 1
        }

        head
            .filter(is_overlaying)
            .append('text')
            .text(function(d){
                var key = d.pos + ':' + d.value
                return head_groups[key].length
            })
            .attr('fill', function(d){
                var head_color = config.mutations_color_map[d.category]
                return (is_color_dark(head_color) ? 'white' : 'black')
            })

        head
            .filter(is_overlaying)
            .on('mouseover', function(d){

                // make hover popup
                var key = d.pos + ':' + d.value
                var head_group = head_groups[key]

                var width_per_head = posToX(1) * get_constant_scale()
                var width = head_group.length * width_per_head

                var shift = width_per_head / 2 - width / 2

                for(var i = 0; i < head_group.length; i++)
                {
                    var needle_id = head_group[i]
                    var head_id = 'h_' + needle_id
                    var head = d3.select('#' + head_id)


                    head
                        .transition()
                        .ease('quad')
                        .duration(config.animations_speed)
                        .attr('transform', function(d) {
                            return transform_needle_head(d, shift)
                        })

                    shift += width_per_head
                }
            })

        return needles
    }

    function createPlot()
    {
        zoom = prepareZoom(config.min_zoom, config.max_zoom, zoomAndMove)

        svg = prepareSVG(config.element)
            .call(zoom)

        // we don't want to close tooltips after panning (which is set to emit
        // stopPropagation on start what allows us to detect end-of-panning events)
        svg.on('click', function(){
            if(d3.event.defaultPrevented) d3.event.stopPropagation()
        })

		paddings = svg.append('g')
			.attr('class', 'paddings')
			.attr('transform', 'translate(' + config.paddings.left + ' , 0)')

		vertical_scalable = paddings.append('g')
			.attr('class', 'vertical scalable')

        leftPadding = paddings.append('rect')
            .attr('fill', 'white')
            .attr('width', config.paddings.left)
			.attr('transform', 'translate(-' + config.paddings.left + ' , 0)')

        if(config.use_log)
        {
            axes.y.scale = d3.scale.log()
                .base(10)
                // we have to avoid exact 0 on scale_min
            axes.y.setDomain(config.y_scale_min || Number.MIN_VALUE, config.y_scale_max)
        }
        else
        {
            axes.y.scale = d3.scale.linear()
            axes.y.setDomain(0, config.y_scale_max)
        }

        axes.y.scale.
            nice()

        var format

        if(config.use_log)
        {
            var cnt = -1
            var labels_count_in_log = config.height / 40
            var ticks_cnt = axes.y.scale.ticks().length
            if (ticks_cnt > labels_count_in_log)
                config.log_ticks_per_label = Math.round(ticks_cnt / labels_count_in_log)
            else
                config.log_ticks_per_label = ticks_cnt

            format = function(d){
                cnt += 1

                if(cnt % config.log_ticks_per_label !== 0)
                    return ''

                d /= 100
                if(d < 0.0001)
                    return d3.format('.3%')(d)
                if(d < 0.001)
                    return d3.format('.2%')(d)
                if(d < 0.01)
                    return d3.format('.1%')(d)
                return d3.format('%')(d)
            }
        }
        else
        {
          format = d3.format('d')
        }

        axes.y.createObj('left')

        axes.y.obj
            .tickFormat(format)
            .tickSubdivide(0)

        axes.y.createGroup('y')

        axes.x.scale = d3.scale.linear()
        axes.x.setDomain(0, config.sequenceLength)

        axes.x.createObj('bottom')
        axes.x.createGroup('x')

        vis = vertical_scalable.append('g')

        if(config.legends.x)
        {
            legend.x.obj = paddings.append('text')
                .attr('class', 'label')
                .text(config.legends.x)
                .attr('x', config.width / 2)
                .attr('y', config.height - config.paddings.bottom)
                .attr('dy','2.4em')
                .style('text-anchor','middle')
        }

        if(config.legends.y)
        {
            legend.y.obj = paddings.append('text')
                .attr('class', 'label')
                .text(config.legends.y)
                .style('text-anchor','middle')
        }

        var needle_tooltip = Tooltip()
        needle_tooltip.init({
            id: 'needle',
            template: config.needle_tooltip
        })

        needles = create_needles(vis, needle_tooltip)

        var site_tooltip = Tooltip()

        site_tooltip.init({
            id: 'site',
            template: config.site_tooltip,
            viewport: config.element.parentNode
        })

        dispatch.on('zoomAndMove', function(){
            needle_tooltip.moveToElement()
            site_tooltip.moveToElement()
        })

        sites = vis.selectAll('.site')
            .data(config.data.sites)
            .enter()
            .append('g')
            .attr('class', function(d)
                {
                    if(d.type.indexOf(',') === -1)
                        return 'site '+ d.type
                    else
                        return 'site multi_ptm'
                }
            )
            .call(site_tooltip.bind)

        sites
            .append('path')
            .attr('d', d3.svg.symbol().size(1).type('triangle-up'))

        site_boxes = sites
			.append('rect')
			.attr('height', config.site_height)

        _rescalePlot()

        config.onload()
    }

	function _setPosition(new_position, stop_callback)
	{
		var boundary = posToX(axes.x.getShiftLimit()) * scale

		if(new_position > 0)
			position = 0
		else if(new_position < boundary)
			position = boundary
		else
			position = new_position

        // let d3 know that we changed the position
        zoom.translate([position, 0])

        if(!stop_callback && config.position_callback)
        {
            var aa_position = xToPos(position)
            config.position_callback(aa_position, true)
        }

	}


    function canvasAnimated(animate)
    {
        var t;
        if(animate)
        {
		    t = svg
			    .transition().ease('quad').duration(config.animations_speed)
        }
        else
        {
            t = svg
        }
        return t
    }

    function changeTicksCount(ticks_count)
    {
        axes.x.obj.ticks(ticks_count)
        canvasAnimated(true).select('.x.axis').call(axes.x.obj)
    }

    function transform_needle_head(d, x_pos)
    {
        if(!x_pos)
            x_pos = 0
        return 'translate('  + [x_pos, axes.y.scale(d.value)] + ')scale(1, '+ scale +')'
    }

    function get_constant_scale()
    {
        return config.max_zoom / scale
    }

    function adjustContent(animate)
    {
        if(scale === config.max_zoom)
        {
            changeTicksCount(20)
        }
        else if(axes.x.obj.ticks() !== 10)
        {
            changeTicksCount(10)
        }
        var constant_scale = get_constant_scale()

        var canvas = canvasAnimated(animate)
		canvas.select('.vertical.scalable').attr('transform', 'translate(' + position + ', 0)scale(' + scale + ', 1)')

        needles.selectAll('.head')
            .attr('transform', transform_needle_head)

        sites.selectAll('path, rect')
            .attr('stroke-width', posToX(1) / 10 + 'px')

        sites.selectAll('path')
            .attr('transform', function(d)
                {
                    // shift by -2 in y axis is meant to lay the shape
                    // on top of site box (it's size_of_shape/2 = 4/2 = 2)
                    return 'translate(' + [posToX((d.end - d.start) / 2), -2] + ')scale(' + [posToX(1), 4] + ')'
                }
            )

        var head_size = posToX(1) / 2 * constant_scale
        needles.selectAll('circle')
            .attr('r', head_size + 'px')
        needles.selectAll('text')
            .attr('font-size', head_size * 2 + 'px')
            .attr('dx', -head_size/2 + 'px')
            .attr('dy', +head_size/2 + 'px')
    }

	function posToX(pos)
	{
		return pos * unit
	}

    function xToPos(coord)
    {
        return -(coord / unit) / scale
    }

    function adjustXAxis(animate)
    {
        var canvas = canvasAnimated(animate)
        var start_position = xToPos(position)
        axes.x.moveTo(start_position)
		canvas.select('.x.axis').call(axes.x.obj)
    }

    function refresh(animate)
    {
        adjustXAxis(animate)
        adjustContent(animate)
    }

    function zoomAndMove()
    {
		_setZoomAndMove(d3.event.scale, d3.event.translate[0])
    }

    function _setZoomAndMove(new_scale, new_position, animate)
    {
        _setPosition(new_position, true)
        _setZoom(new_scale, true)

        if(config.zoomAndMove_callback)
        {
            var aa_position = xToPos(position)
            config.zoomAndMove_callback(scale, aa_position, true)
        }

        refresh(animate)
        dispatch.zoomAndMove(this)
    }

	function _setZoom(new_scale, stop_callback)
	{
        if(scale === new_scale)
            return

		scale = new_scale

        // if we have a callback, release it (unless explicitly asked to refrain)
        if(!stop_callback && config.zoom_callback)
        {
            config.zoom_callback(scale, true)
        }
        // if we are not issuing a callback, that the function was called by callback,
        // then we want to assure that all related components are aware of zoom update
        else
        {
            // let d3 know that the zoom was changed
			zoom.scale(scale)

            // recalculate position so we do not exceed boundaries
            _setPosition(position)

            // adjust axes
            refresh(true)
        }

	}

    var publicSpace = {
        init: function(new_config)
        {
            configure(new_config)
			scaleToNeedles()
            createPlot()

        },
        setZoom: _setZoom,
		setPosition: _setPosition,
        setAAPosition: function(aa_position, stop_callback, animate)
        {
            var converted_position = posToX(-aa_position) * scale
            _setPosition(converted_position, stop_callback)
            refresh(animate)
        },
        setSize: function(width, height, max_zoom)
        {
            config.width = width
            config.height = height
            config.max_zoom = max_zoom

            _adjustPlotDimensions()

            _rescalePlot()

            // refresh zoom and position with current values
            _setZoomAndMove(scale, position, true)
        },
        destroy: function()
        {
            svg.remove();
            //var element = svg.node()
            //element.parentNode.removeChild(element);
        }
    }

    return publicSpace
}
