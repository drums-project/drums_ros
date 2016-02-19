# Install InfluxDB 1.x as the time-series Database backend

1. I followed this guide: https://influxdata.com/downloads/#influxdb (v0.10.1)

2. Usage: `sudo service influxdb start|stop|restart`

3. Enable `graphite` importer for InfluxDB

```
$ sudo vim /etc/influxdb/influxdb.conf
# find the Graphite section and edit it to:

[[graphite]]
  enabled = true
  database = "drums_ros"
  bind-address = ":2013"
  protocol = "tcp"
  consistency-level = "one"
  name-separator = "."

```

4. Restart `influxdb`: `sudo service influxdb restart`

- Web dashboard (almost useless): `http://localhost:8083`
- API Backend (important): `http://localhost:8086`
- CLI: `influx`

# Install and configure `grafana`

1. I basically followed this guide: http://docs.grafana.org/installation/debian/ (the `.deb` method)

- Web front-end: `http://localhost:3000`
- Default user/pass: admin/admin
- Config file: `/etc/grafana/grafana.ini`
- Usage: `sudo service grafana-server start|stop|restart`

2. Add an `influxdb 0.9.x` data source to grafana: http://docs.grafana.org/datasources/influxdb/

- URL is `http://localhost:8086`
- Database name is: `drums_ros` (Has been set in the previous step)
- User/pass is by default: `admin/admin`

## Notes

When `drums_ros` is running and exporting data to `TCP 2013`, `influxdb` captures those data to the `drums_ros` database. You may need to configure the settings of this database to your needs (e.g retention policies). To verify the backend, make sure that `drums_ros` is exporting its data correctly by running `netcat -lp 2013`, then verify the database is created on `influxdb` side by using their web dashboard on `http://localhost:8083`. If everything is up, you should be able to create dashboards on `grafana` and use `drums_ros` datasource for queries.