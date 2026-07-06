local json = require "cjson"
local state_dict = ngx.shared.bluegreen_state

local function init_state()
    if not state_dict:get("active") then
        state_dict:set("active", "blue")
        state_dict:set("standby", "green")
        state_dict:set("switching", "false")
        state_dict:set("last_switch", "0")
    end
end

local function atomic_switch()
    local switching = state_dict:get("switching")
    if switching == "true" then
        return nil, "switch already in progress"
    end
    state_dict:set("switching", "true")
    local active = state_dict:get("active")
    local standby = state_dict:get("standby")
    state_dict:set("active", standby)
    state_dict:set("standby", active)
    state_dict:set("last_switch", tostring(ngx.time()))
    state_dict:set("switching", "false")
    return { previous = active, current = standby, timestamp = ngx.time() }, nil
end

local function get_state()
    return {
        active = state_dict:get("active"),
        standby = state_dict:get("standby"),
        switching = state_dict:get("switching"),
        last_switch = tonumber(state_dict:get("last_switch") or "0")
    }
end

local function handle_request()
    init_state()
    local method = ngx.req.get_method()
    local uri = ngx.var.uri

    if uri == "/_bg/status" and method == "GET" then
        ngx.say(json.encode(get_state()))
        return
    end

    if uri == "/_bg/switch" and method == "POST" then
        if ngx.var.ssl_client_verify ~= "SUCCESS" then
            ngx.status = 403
            ngx.say(json.encode({ error = "mTLS required" }))
            return
        end
        local result, err = atomic_switch()
        if err then
            ngx.status = 409
            ngx.say(json.encode({ error = err }))
            return
        end
        ngx.say(json.encode(result))
        return
    end

    ngx.status = 404
    ngx.say(json.encode({ error = "not found" }))
end

handle_request()
