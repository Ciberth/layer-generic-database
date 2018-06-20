#!/usr/bin/python

import pwd
import os
from subprocess import call
from charmhelpers.core import host, hookenv
from charmhelpers.core.hookenv import log, status_set, config
from charmhelpers.core.templating import render
from charms.reactive import when, when_not, set_flag, clear_flag, when_file_changed, endpoint_from_flag
from charms.reactive import Endpoint


# Once this generic database becomes concrete the following dictionary will keep all information
# Config-changed hook sometimes fails if keys do not exist (?)

db_details = {}
db_details['technology'] = "placeholder"
db_details['dbname'] = "placeholder"
db_details['user'] = "placeholder"
db_details['host'] = "placeholder"
db_details['password'] = "placeholder"
db_details['port'] = "placeholder"

################################################
#                                              #
# Apache stuff                                 #
#                                              #
################################################


@when('apache.available')
@when_not('gdb.configured')
def finishing_up_setting_up_sites():
    host.service_reload('apache2')
    set_flag('apache.start')

@when('apache.start')
@when_not('gdb.configured')
def ready():
    host.service_reload('apache2')
    status_set('active', 'apache ready - gdb not concrete')

###############################################
#
# Postgresql support
#
###############################################


@when('pgsqldb.connected', 'endpoint.generic-database.postgresql.requested')
def request_postgresql_db():
    db_request_endpoint = endpoint_from_flag('endpoint.generic-database.postgresql.requested')
    databasename = db_request_endpoint.databasename()

    # Check if gdb is concrete and if databasename equals the request 
    # if so share details
    if 'concrete' in db_details:
        if databasename == db_details['dbname']:
            gdb_endpoint = endpoint_from_flag('endpoint.generic-database.postgresql.requested')
    
            gdb_endpoint.share_details(
                "postgresql",
                db_details['host'],
                db_details['dbname'],
                db_details['user'],
                db_details['password'],
                db_details['port'],
            )
            status_set('active', 'Shared details!')
            clear_flag('endpoint.generic-database.postgresql.requested')
    else: # not concrete
        pgsql_endpoint = endpoint_from_flag('pgsqldb.connected')
        pgsql_endpoint.set_database(databasename)
        status_set('maintenance', 'Requesting pgsql db')


@when('pgsqldb.master.available', 'endpoint.generic-database.postgresql.requested')
@when_not('endpoint.generic-database.concrete')
def render_pgsql_config_and_share_details():   
    pgsql_endpoint = endpoint_from_flag('pgsqldb.master.available')
    
    # fill dictionary 
    db_details['technology'] = "postgresql"
    db_details['password'] = pgsql_endpoint.master['password']
    db_details['dbname'] = pgsql_endpoint.master['dbname']
    db_details['host'] = pgsql_endpoint.master['host']
    db_details['user'] = pgsql_endpoint.master['user']
    db_details['port'] = pgsql_endpoint.master['port']
    db_details['concrete'] = True

    # On own apache
    render('gdb-config.j2', '/var/www/generic-database/gdb-config.html', {
        'db_master': pgsql_endpoint.master,
        'db_pass': pgsql_endpoint.master['password'],
        'db_dbname': pgsql_endpoint.master['dbname'],
        'db_host': pgsql_endpoint.master['host'],
        'db_user': pgsql_endpoint.master['user'],
        'db_port': pgsql_endpoint.master['port'],
    })
    # share details to consumer-app
    gdb_endpoint = endpoint_from_flag('endpoint.generic-database.postgresql.requested')
    
    gdb_endpoint.share_details(
        "postgresql",
        pgsql_endpoint.master['host'],
        pgsql_endpoint.master['dbname'],
        pgsql_endpoint.master['user'],
        pgsql_endpoint.master['password'],
        pgsql_endpoint.master['port'],
    )
    
    clear_flag('endpoint.generic-database.postgresql.requested')
    set_flag('endpoint.generic-database.postgresql.available')
    set_flag('endpoint.generic-database.concrete')
    set_flag('restart-app')


###############################################
#
# Mysql support
#
###############################################

# This is done in 2 phases over 2 relations (mysql-shared and mysql-root)
# Mysql-shared handles the database request 1.
# Mysql-root handles the creation of (root) user that can access the database on remote nodes 2.


### 1. Mysql-shared

@when('mysql-shared.connected', 'endpoint.generic-database.mysql.requested')
@when_not('mysqlshared.configured')
def request_mysql_db():
    db_request_endpoint = endpoint_from_flag('endpoint.generic-database.mysql.requested')
    databasename = db_request_endpoint.databasename()

    mysql_endpoint = endpoint_from_flag('mysql-shared.connected')
    mysql_endpoint.configure(databasename, 'proxy_temp_user', prefix="proxy")
    status_set('maintenance', 'Requesting mysql db')

@when('mysql-shared.available', 'endpoint.generic-database.mysql.requested')
@when_not('mysqlshared.configured')
def render_mysql_config():   
    mysql_endpoint = endpoint_from_flag('mysql-shared.available')
    
    # fill dictionary (only dbname, location, port)
    db_details['technology'] = "mysql"
    db_details['dbname'] = mysql_endpoint.database("proxy")
    db_details['host'] = mysql_endpoint.db_host()
    db_details['port'] = "3306" # note no port :/
    db_details['concrete'] = True

    # On own apache
    render('gdb-config.j2', '/var/www/generic-database/mysql-shared-config.html', {
        'db_pass': mysql_endpoint.password("proxy"),
        'db_dbname': mysql_endpoint.database("proxy"),
        'db_host': mysql_endpoint.db_host(),
        'hostname': mysql_endpoint.hostname("proxy"),
        'db_user': mysql_endpoint.username("proxy"),
    })


    host.service_reload('apache2')
    set_flag('mysqlshared.configured')
    status_set('active', 'mysql shared done!')

### 2.


@when('mysql-root.connected', 'endpoint.generic-database.mysql.requested')
@when_not('mysqlroot.configured')
def request_mysql_root_user():
    status_set('maintenance', 'Requesting mysql root user')

@when('mysql-root.available', 'endpoint.generic-database.mysql.requested')
@when_not('webapp.mysqlroot.configured')
def render_mysql_root_config():
    mysqlroot_endpoint = endpoint_from_flag('mysql-root.available')

    # fill dictionary (user and password)
    db_details['technology'] = "mysql"
    db_details['password'] = mysqlroot_endpoint.password()
    db_details['user'] = mysqlroot_endpoint.user()
    db_details['concrete'] = True

    # On own apache
    render('gdb-config.j2', '/var/www/generic-database/mysql-root-config.html', {
        'db_pass': mysqlroot_endpoint.password(),
        'db_dbname': mysqlroot_endpoint.database(),
        'db_host': mysqlroot_endpoint.host(),
        'db_user': mysqlroot_endpoint.user(),
        'db_port': mysqlroot_endpoint.port(),
    })


    host.service_reload('apache2')
    set_flag('mysqlroot.configured')
    status_set('active', 'mysql-root done!')


@when('mysqlshared.configured', 'mysqlroot.configured', 'endpoint.generic-database.mysql.requested')
def share_details():
    gdb_endpoint = endpoint_from_flag('endpoint.generic-database.mysql.requested')
    
    gdb_endpoint.share_details(
        "mysql",
        db_details['host'],
        db_details['dbname'],
        db_details['user'],
        db_details['password'],
        db_details['port'],
    )
    
    clear_flag('endpoint.generic-database.mysql.requested')
    set_flag('endpoint.generic-database.mysql.available')
    set_flag('endpoint.generic-database.concrete')
    set_flag('restart-app')

#######################
#
# MongoDB
#
#######################

@when('mongodb.connected', 'endpoint.generic-database.mongodb.requested')
@when_not('endpoint.generic-database.mongodb.available', 'endpoint.generic-database.concrete')
def request_mongodb():
    mongodb_ep = endpoint_from_flag('mongodb.connected')
    mongodb_connection = mongodb_ep.connection_string()

    mongo_host = mongodb_connection.split(':')[0]
    mongo_port = mongodb_connection.split(':')[1]

    gdb_endpoint = endpoint_from_flag('endpoint.generic-database.mongodb.requested')

    # fill dictionary (user and password)
    db_details['technology'] = "mongodb"
    db_details['password'] = "not supported on mongodb interface"
    db_details['dbname'] = gdb_endpoint.databasename()
    db_details['host'] = mongo_host
    db_details['user'] = "not supported on mongodb interface"
    db_details['port'] = mongo_port
    db_details['concrete'] = True


    # On own apache
    render('gdb-config.j2', '/var/www/generic-database/mysql-root-config.html', {
        'db_pass': db_details['password'],
        'db_dbname': db_details['dbname'],
        'db_host': db_details['host'],
        'db_user': db_details['user'],
        'db_port': db_details['port'],
    })

    
    gdb_endpoint.share_details(
        "mongodb",
        mongo_host,
        gdb_endpoint.databasename(),
        "not supported on mongodb interface",
        "not supported on mongodb interface",
        mongo_port,
    )
    
    clear_flag('endpoint.generic-database.mongodb.requested')
    set_flag('endpoint.generic-database.mongodb.available')
    set_flag('endpoint.generic-database.concrete')
    set_flag('restart-app')

@when('mongodb.connected', 'endpoint.generic-database.mongodb.requested', 'endpoint.generic-database.concrete')
def connect_to_concrete_mongodb():
    gdb_endpoint = endpoint_from_flag('endpoint.generic-database.mongodb.requested')
    gdb_endpoint.share_details(
        db_details['technology'],
        db_details['host'],
        db_details['dbname'],
        db_details['user'],
        db_details['password'],
        db_details['port'],
    )

    clear_flag('endpoint.generic-database.mongodb.requested')
    status_set('active', 'Shared mongodb details!')


@when('restart-app')
def restart_app():
    host.service_reload('apache2')
    clear_flag('restart-app')
    status_set('active', 'Apache/gdb ready and concrete')


