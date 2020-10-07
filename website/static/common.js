function append(destination, new_content)
{
    Array.prototype.push.apply(destination, new_content)
}

function update_object(modified_obj, modifying_obj)
{
    $.extend(modified_obj, modifying_obj)
}

/**
 * If property of given 'name' in 'new_config' object is an URL string,
 * perform asynchronous GET call to replace the property with JSON object
 * returned by the endpoint defined by the URL string.
 *
 * Warning: current implementation assumes that all string values are URL strings.
 *
 * @param {Object} new_config
 * @param {Object} name
 * @param {function} callback - a function to be called after the data was loaded
 * (or if there was no need to load additional data - i.e. the property was not an URL string)
 */
function get_remote_if_needed(new_config, name, callback)
{
    var value = new_config[name]
    if(typeof value === 'string')
    {
		$.get({
			url: value,
			success: function(data)
			{
				new_config[name] = data
                if(callback)
                {
                    return callback()
                }
			}
		})
    }
    else
    {
        if(callback)
        {
            return callback()
        }

    }
}


function get_url_params()
{
    // in future URLSearchParams would do the job
    var params_string = decodeURIComponent(window.location.search)
    params_string = params_string.substr(1) // remove '?' character from the beginning
    var params_list = params_string.split('&')
    var params = {}
    for(var i = 0; i < params_list.length; i++)
    {
      var param = params_list[i].split('=')
      var key = param[0]
      var value = param[1]
      if(key)
        params[key] = value
    }
    return params
}


function affix(element, bottom_element)
{
    // fix the width (so it's set in pixels)
    element.css('position', 'static');
    element.css('width', '');
    element.width(element.width());
    element.css('position', '');

    element.affix({
        offset: {
            top: function () {
                return (this.top = element.offset().top)
            },
            bottom: function () {
                return (this.bottom = bottom_element.outerHeight())
            }
        }
    })

    var parent = $(element.parent());

    function update_min_height()
    {
        element.css('position', 'static');
        parent.css('min-height', '');
        parent.css('min-height', parent.height())
        element.css('position', '');
    }
    update_min_height();
    element.on('PotentialAffixChange', update_min_height);

    $(window).on(
        'resize', function()
        {
            affix(element, bottom_element)
        }
    )
}


$('body').off().on('click', '.list-expand', function(){
    var elem = $(this)
    var parent = $(elem.parent())
    parent.toggleClass('list-collapsed')
    if(elem.text() === 'more')
        elem.text('less')
    else
        elem.text('more')
    parent.trigger('PotentialAffixChange');
    return false
})

/* Just for debug purposes */
var p = console.log

/**
 * Simple substitution formatting tool - not such powerful as nunjucks.renderString but very light.
 * [As slim version of nunjucks is used on production, renderString is not available.]
 * See: {@link https://github.com/mozilla/nunjucks/issues/163}.
 * @param {string} template
 * @param {Object} variables
 * @returns {string}
 */
function format(template, variables)
{
    return template.replace(
        /{{ (\w+) }}/g,
        function (full_match, match) {
            if (!(match in variables)) {
                console.warn(match, 'not found in', variables, 'for', template);
            }
            return variables[match]
        }
    );
}

function set_csrf_token(token)
{
    $.ajaxPrefilter(function(options, originalOptions, jqXHR) {
        jqXHR.setRequestHeader('X-Csrftoken', token);
    })
}


function decode_url_pattern(flask_url_pattern)
{
    return decodeURIComponent(flask_url_pattern).replace(/\+/g, ' ');
}

function flash(message, category) {
    if(!category)
        category = 'warning'
    $('.flashes').append('<div class="alert alert-' + category + '" role="alert">' + message + ' </div>')
}
