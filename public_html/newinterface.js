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
    for (var item in data) {
        if (item.substr(0, 7) == "lfbuild") {
            var arch = item.substr(8);
            var connecttype;
            if (!data[item]["connected"]) {
                connecttype = "offline";
            } else if (data[item]["runningBuilds"].length == 0) {
                connecttype = "idle";
            } else {
                connecttype = "running";
                var buildItem = data[item]["runningBuilds"][0];
                update_builder_status(buildItem["builderName"]);
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
    for (var item in data) {
        if (item.substr(0, 7) == "lfbuild") {
            var arch = item.substr(8);
            archs.push(arch);

            for (var builder in data[item]["builders"]) {
                var project = builder.substr(0, builder.lastIndexOf("-"));
                if (!(project in projects)) {
                    projects[project] = new Object();
                }
                projects[project][arch] = "&nbsp;";
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
                update_builder_status(builder);
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
                    window.setTimeout(update_builder_status, 15000, [builder]);
                } else if (data["results"] == 0) {
                    var build_end = data["times"][1];
                    var now = new Date().getTime() / 1000;
                    var timediff_desc = 
                        get_timediff_description(build_end, now);
                    status_desc = "<a href='builders/" + builder
                        + "'>" + timediff_desc + "</a>";
                    status_class = "success";
                    var timediff = build_end - now;
                    var nextrun;
                    if (timediff < 300) {
                        nextrun = 1;
                    } else if ((timediff >= 300) && (timediff < 3600)) {
                        nextrun = 5;
                    } else {
                        nextrun = 30;
                    }
                    window.setTimeout(update_builder_status, nextrun * 60000,
                                      [builder]);
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
        });
}

function do_refresh() {
    load_new_data();
    window.setTimeout(do_refresh, 15000);
}

$(document).ready(function(data) {
        $.ajax({
                url: "json/slaves/",
                success: function(data) {
                    create_status_table(data);
                    load_slaveinfo(data);
                    window.setTimeout(do_refresh, 15000);
                }
            });
    });