(function($) {
    $(function() {
        var pinned = {};
        $('dl.server').hide();
        $('dd.servers li').hover(
            function(e) {
                $(this).find('dl.server').delay(100).show(150);
                var sel = 'span.resused.' + $(this).find('span.serverid').text();
                $(this).parents('div.hypervisor').find(sel).addClass('highlighted');
            },
            function(e) {
                $(this).find('dl.server').stop(true).hide(150);
                var sel = 'span.resused.' + $(this).find('span.serverid').text();
                $(this).parents('div.hypervisor').find(sel).removeClass('highlighted');
            }
        );
        $('#hypervisors > li').hover(
            function(e) {
                $(this).find('div').show();
            },
            function(e) {
                if(! ($(this).index() in pinned)) {
                    $(this).find('div.hypervisor').hide();
                }
            }
        );
        $('#hypervisors > li').mousemove(function(e) {
            if($(this).is('#hypervisors > li') && !($(this).index() in pinned)) {
                $(this).find('div').css('top', e.pageY+10).css('left', e.pageX+10);
            }
        });
        $('#hypervisors > li').click(function(e) {
            if($(e.target).is('#hypervisors > li') || $(e.target).parent('#hypervisors > li').length > 0) {
                var i = $(this).index();
                if(i in pinned) {
                    delete pinned[i];
                } else {
                    pinned[i] = true;
                }
            }
        });
        $('html').click(function(e) {
            if(! ($(e.target).is('ul#hypervisors') || $(e.target).parents('ul#hypervisors').length > 0)) {
                pinned = {};
                $('div.hypervisor').hide();
            }
        });
        $('#search input').on('search input', function(e) { // 'search' event is nonstandard, maybe use 'input'
            $('#hypervisors > li').removeClass('searched');
            if(this.value) {
                $('#hypervisors > li').filter(function(index) {
                    return $('.searchtext', this).text().toLowerCase().indexOf(e.target.value.toLowerCase()) != -1;
                }).addClass('searched');
            }
        });
    });
})(jQuery);
