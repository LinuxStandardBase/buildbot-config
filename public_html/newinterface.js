var timers = new Object();

function get_timediff_description(start, end) {
    var timediff = Math.floor(end - start);
    var timediff_byunit;
    var timeunit;
    var timedesc;
    if (timediff >= 86400) {
        timediff_byunit = (timediff - (timediff % 86400)) / 86400;
        timeunit = "day";
    } else if (timediff >= 3600) {
        timediff_byunit = (timediff - (timediff % 3600)) / 3600;
        timeunit = "hour";
    } else if (timediff >= 60) {
        timediff_byunit = (timediff - (timediff % 60)) / 60;
        timeunit = "minute";
    } else {
        timedesc = "just now";
    }
    if (timedesc != "just now") {
        timedesc = timediff_byunit + " " + timeunit;
        if (timediff_byunit > 1) {
            timedesc += "s";
        }
        timedesc += " ago";
    }
    return timedesc;
}

function load_slaveinfo(data) {
    var items = "";
    var load_interval = 0.1;
    for (var item in data) {
        if (item.substr(0, 7) == "lfbuild") {
            var arch = item.substr(8);
            var connecttype;
            if (!data[item]["connected"]) {
                connecttype = "offline";
            } else if (data[item]["runningBuilds"].length > 0) {
                connecttype = "running";
                var buildItem = data[item]["runningBuilds"][0];
                set_builder_refresh(buildItem["builderName"],
                                    load_interval * 1000);
                load_interval = load_interval + 0.1;
            } else {
                connecttype = "idle";
            }
	    $("#heading-" + arch).html(arch + "<br />" + connecttype).attr("class", connecttype);
        }
    }
}

function load_new_data() {
    $.ajax({
        url: "json/slaves/",
        success: function(data) {
            load_slaveinfo(data);
        }
    });
}

function create_status_table(data) {
    var archs = new Array();
    var projects = new Object();
    var load_interval = 0.1;
    for (var item in data) {
        if (item.substr(0, 7) == "lfbuild") {
            var arch = item.substr(8);
            archs.push(arch);

            for (var builder in data[item]["builders"]) {
                var project = builder.substr(0, builder.lastIndexOf("-"));
                if (!(project in projects)) {
                    projects[project] = new Object();
                }
                projects[project][arch] = "unknown";
            }
        }
    }
    var status_table = "<table>\n  <tr>\n    <th></th>\n";
    archs.forEach(function(arch) {
        status_table += "    <th id='heading-" + arch + "'>" + arch
	    + "<br />unknown</th>\n";
    });
    status_table += "  </tr>\n";
    for (var project in projects) {
        status_table += " <tr>\n    <th>" + project + "</th>\n";
        archs.forEach(function(arch) {
            var arch_item;
            var builder = project + "-" + arch;
            if (arch in projects[project]) {
                arch_item = projects[project][arch];
                set_builder_refresh(builder, load_interval * 1000);
                load_interval = load_interval + 0.1;
            } else {
                arch_item = "&nbsp;";
            }
            status_table += "    <td id='" + builder + "'>" 
                + arch_item + "</td>\n";
        });
        status_table += " </tr>\n";
    }
    status_table += "</table>\n";
    $("#status_table").html(status_table);
}

function set_builder_refresh(builder, interval) {
    var currentTime = new Date().getTime();
    var setNewTimer = false;

    if (timers.hasOwnProperty(builder)) {
        var timeoutHandle = timers[builder][0];
        var timeoutFireTime = timers[builder][1];
        if ((currentTime > timeoutFireTime) || 
            ((currentTime + interval) < timeoutFireTime)) {
            window.clearTimeout(timeoutHandle);
            setNewTimer = true;
        }
    } else {
        setNewTimer = true;
    }

    if (setNewTimer) {
        timers[builder] = [window.setTimeout(update_builder_status, interval,
                                             [builder]),
                           currentTime + interval];
    }
}

function update_builder_status(builder) {
    $.ajax({
            url: "json/builders/" + builder + "/builds/-1",
            success: function(data) {
                var status_desc;
                var status_class;
                if (data["currentStep"] != null) {
                    var step_name = data["currentStep"]["name"];
                    status_desc = "<a href='builders/" + builder
                        + "/builds/" + data["number"] + "'>"
                        + step_name + "</a>";
                    status_class = "running";
                    set_builder_refresh(builder, 15000);
                } else if (data["results"] == 0) {
                    var build_end = data["times"][1];
                    var now = new Date().getTime() / 1000;
                    var timediff_desc = 
                        get_timediff_description(build_end, now);
                    status_desc = "<a href='builders/" + builder
                        + "'>" + timediff_desc + "</a>";
                    status_class = "success";
                    var timediff = now - build_end;
                    var nextrun;
                    if (timediff < 300) {
                        nextrun = 1;
                    } else if ((timediff >= 300) && (timediff < 3600)) {
                        nextrun = 5;
                    } else {
                        nextrun = 30;
                    }
                    set_builder_refresh(builder, nextrun * 60000);
                } else if (data["results"] == 2) {
                    status_desc = "<a href='builders/" + builder
                        + "/builds/" + data["number"] + "'>"
                        + data["text"].join(" ") + "</a>";
                    status_class = "failure";
                } else {
                    status_desc = "unknown: " + data["results"];
                    status_class = "none";
                }
                $("#" + builder).html(status_desc).attr('class', status_class);
            },
            error: function() {
                $("#" + builder).html("error getting status").attr('class', 'none');
                set_builder_refresh(builder, 15000);
            },
        });
}

$(document).ready(function(data) {
        $.ajax({
                url: "json/slaves/",
                success: function(data) {
                    create_status_table(data);
                    load_slaveinfo(data);
                    window.setInterval(load_new_data, 15000);
                }
            });
    });
