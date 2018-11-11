#!/usr/bin/env python
import os
import sys
import time
import hashlib
from xml.dom import minidom

TEMP_DIR = '/tmp'

MODULE_TEMPLATE = """
import rospy
import lcm

# import ROS/LCM messages
{msgs_import}

class ROS4LCM_BridgeModule(object):
    # global objects
    module_name = None
    lcmpy = None

    def __init__(self, direction):
        self.module_name = '%s_bridge_module' % direction

        # init ROS
        rospy.loginfo(self.module_name + "Initializing ROS...")
        rospy.init_node(self.module_name)
        rospy.loginfo(self.module_name + "Done!")

        # init LCM
        rospy.loginfo(self.module_name + "Initializing LCM...")
        self.lcmpy = lcm.LCM()
        rospy.loginfo(self.module_name + "Done!")

        # publishers
{publishers}

    # define callback functions
{callbacks}

    def start():
        # subscribe
{subscribers}

        # keep spinning
        try:
            while {spinning_condition}:
{spinning_call}
        except KeyboardInterrupt:
            pass

#if __name__ == '__main__':
#    bridge = ROS4LCM_BridgeModule('{direction}')
#    bridge.start()
"""

HELP = """
Usage:
    python ros4lcm_bridge.py [options]

Options:
    -d (--direction)    Indicates the direction of the bridge.
                        It can be either `ros2lcm` or `lcm2ros`.

"""

IN_REQUIRED_FIELDS = {
    'ros2lcm' : ['name', 'pkg', 'type', 'queue_size'],
    'lcm2ros' : ['name', 'pkg', 'type']
}
OUT_REQUIRED_FIELDS = {
    'ros2lcm' : ['name', 'pkg', 'type'],
    'lcm2ros' : ['name', 'pkg', 'type', 'queue_size', 'latched']
}
IN_MSG_IMPORT_SUFFIX = {
    'ros2lcm' : '.msg',
    'lcm2ros' : ''
}
OUT_MSG_IMPORT_SUFFIX = {
    'ros2lcm' : '',
    'lcm2ros' : '.msg'
}
CALLBACK_PROTO = {
    'ros2lcm' : 'def %s(data):',
    'lcm2ros' : 'def %s(channel, data):'
}
CALLBACK_CONFIGURE = {
    'ros2lcm' : 'out_msg = %s()',
    'lcm2ros' : 'in_msg = %s.decode(data)'
}
CALLBACK_PUBLISH = {
    'ros2lcm' : '%s.publish("%s", out_msg.encode())',
    'lcm2ros' : '%s.publish(out_msg)'
}
SPINNING_CONDITION = {
    'ros2lcm' : 'not rospy.is_shutdown()',
    'lcm2ros' : 'True'
}
SPINNING_CALL = {
    'ros2lcm' : 'rospy.spin()',
    'lcm2ros' : 'self.lcmpy.handle()'
}
INDENT = ''.join([' ']*4)
PUBLISHER_INDENT = 2
SUBSCRIBER_INDENT = 2
SPIN_CALL_INDENT = 4
CALLBACK_INDENT = 1

class MAP_TYPE:
    CODE = 1
    FROM_TO = 2

def indent(num):
    return ''.join([INDENT]*num)

CONFIG_FILE = os.path.join( os.path.dirname(os.path.realpath(__file__)), '..', 'config', 'bridge_config.xml')

if __name__ == '__main__':
    # check args
    if len(sys.argv) != 3 or sys.argv[1] not in ['-d', '--direction'] or sys.argv[2] not in ['ros2lcm', 'lcm2ros']:
        print HELP
        exit(-1)
    DIRECTION = sys.argv[2]
    # script placeholders
    IMPORT_MSGS = set()
    PLACEHOLDERS = {
        'direction' : DIRECTION,
        'msgs_import' : [],
        'publishers' : [],
        'callbacks' : [],
        'subscribers' : [],
        'spinning_condition' : SPINNING_CONDITION[DIRECTION],
        'spinning_call' : indent(SPIN_CALL_INDENT) + SPINNING_CALL[DIRECTION]
    }
    # parse config file
    xmldoc = minidom.parse(CONFIG_FILE)
    # make sure that the element ros2lcm exists
    bridges = xmldoc.getElementsByTagName(DIRECTION)
    if len(bridges) != 1:
        print 'FATAL: Invalid configuration, expected 1 element of type <%s>, %d found instead. Exiting...' % (DIRECTION, len(bridges))
        exit(1)
    # check if the direction is enabled
    bridge = bridges[0]
    if bridge.getAttribute('enabled') not in [1, '1', True, 'true']:
        print 'INFO: The bridge direction <%s> is disabled in the configuration file. Exiting...' % DIRECTION
        exit(0)
    # parse bridge configuration
    links = bridge.getElementsByTagName('link')
    disabled_links = 0
    enabled_links = []
    for link in links:
        # check if the link is enabled
        if link.getAttribute('enabled') not in [1, '1', True, 'true']:
            disabled_links += 1
            continue
        # get input channel/topic
        input_chs = link.getElementsByTagName('in')
        if len(input_chs) != 1:
            print 'FATAL: Invalid configuration, expected 1 element of type <in> in element <link>, %d found instead. Exiting...' % len(input_chs)
            exit(2)
        input_ch = input_chs[0]
        # get output channel/topic
        output_chs = link.getElementsByTagName('out')
        if len(output_chs) != 1:
            print 'FATAL: Invalid configuration, expected 1 element of type <out> in element <link>, %d found instead. Exiting...' % len(output_chs)
            exit(3)
        output_ch = output_chs[0]
        # check in and out
        in_fields = IN_REQUIRED_FIELDS[DIRECTION]
        out_fields = OUT_REQUIRED_FIELDS[DIRECTION]
        for field in in_fields:
            if not input_ch.hasAttribute(field) or len(input_ch.getAttribute(field)) <= 0:
                print 'FATAL: Invalid configuration, expected attribute `%s` in element of type <in>. The attribute is either missing or empty. Exiting...' % field
                exit(4)
        for field in out_fields:
            if not output_ch.hasAttribute(field) or len(output_ch.getAttribute(field)) <= 0:
                print 'FATAL: Invalid configuration, expected attribute `%s` in element of type <out>. The attribute is either missing or empty. Exiting...' % field
                exit(5)
        # get link config
        input_ch_name = input_ch.getAttribute('name')
        output_ch_name = output_ch.getAttribute('name')
        # create unique callback id
        link_id = str( hashlib.md5( '%s_%s'%(input_ch_name, output_ch_name) ).hexdigest() )[:5]
        publisher_name = 'pub_%s' % link_id
        callback_name = 'cb_%s' % link_id
        # try to import the input message
        pkg_type_tuple = (input_ch.getAttribute('pkg'), IN_MSG_IMPORT_SUFFIX[DIRECTION], input_ch.getAttribute('type'))
        in_type_import = 'from %s%s import %s' % pkg_type_tuple
        try: exec(in_type_import)
        except ImportError:
            print 'FATAL: An error occurred while importing `%s%s.%s`. Check the configuration and make sure that the message type exists. Exiting...' % pkg_type_tuple
            exit(6)
        IMPORT_MSGS.add( pkg_type_tuple )
        # try to import the output message
        pkg_type_tuple = (output_ch.getAttribute('pkg'), OUT_MSG_IMPORT_SUFFIX[DIRECTION], output_ch.getAttribute('type'))
        out_type_import = 'from %s%s import %s' % pkg_type_tuple
        try: exec(out_type_import)
        except ImportError:
            print 'FATAL: An error occurred while importing `%s%s.%s`. Check the configuration and make sure that the message type exists. Exiting...' % pkg_type_tuple
            exit(6)
        IMPORT_MSGS.add( pkg_type_tuple )
        # create publisher
        if DIRECTION == 'lcm2ros':
            PLACEHOLDERS['publishers'].append(
                indent(PUBLISHER_INDENT) + 'self.%s = rospy.Publisher("%s", %s, queue_size=%s, latched=%s)' % (
                    publisher_name,
                    output_ch_name,
                    output_ch.getAttribute('type'),
                    output_ch.getAttribute('queue_size'),
                    'True' if output_ch.getAttribute('latched') in [1, '1', True, 'true'] else 'False'
                )
            )
        # create subscribers
        if DIRECTION == 'lcm2ros':
            PLACEHOLDERS['subscribers'].append(
                indent(SUBSCRIBER_INDENT) + 'rospy.Subscriber("%s", %s, %s)' % (
                    input_ch_name,
                    input_ch.getAttribute('type'),
                    'self.%s' % callback_name
                )
            )
        else:
            PLACEHOLDERS['subscribers'].append(
                indent(SUBSCRIBER_INDENT) + 'self.lcmpy.subscribe("%s", %s)' % (
                    input_ch_name,
                    'self.%s' % callback_name
                )
            )
        # parse mapping
        mappings = link.getElementsByTagName('mapping')
        if len(mappings) != 1:
            print 'FATAL: Invalid configuration, expected 1 element of type <mapping> in element <link>, %d found instead. Exiting...' % len(mappings)
            exit(7)
        mapping = mappings[0]
        # create callback function
        callback_statements = [
            indent(CALLBACK_INDENT) + CALLBACK_PROTO[DIRECTION] % callback_name
        ]
        # configure callback
        callback_statements.append(
            indent(CALLBACK_INDENT+1) + ( CALLBACK_CONFIGURE[DIRECTION] % input_ch.getAttribute('type') )
        )
        # parse map elements
        maps = mapping.getElementsByTagName('map')
        for map in maps:
            type = None
            if map.hasAttribute('from') and map.hasAttribute('to'):
                type = MAP_TYPE.FROM_TO
            if map.hasAttribute('code'):
                type = MAP_TYPE.CODE
            # check type
            if type is None:
                print 'FATAL: Invalid configuration, expected either attributes (`from`, `to`) or (`code`) in element <map>. Exiting...'
                exit(8)
            # check data
            if type == MAP_TYPE.FROM_TO:
                if len(map.getAttribute('from')) < 1 or len(map.getAttribute('to')) < 1:
                    print 'FATAL: Invalid configuration, expected attributes (`from`, `to`) in element <map>. The attributes are either missing or empty. Exiting...'
                    exit(9)
            if type == MAP_TYPE.CODE:
                if len(map.getAttribute('code')) < 1:
                    print 'FATAL: Invalid configuration, expected attribute `code` in element <map>. The attribute is either missing or empty. Exiting...'
                    exit(10)
            # add mapping to callback
            if type == MAP_TYPE.FROM_TO:
                callback_statements.append(
                    indent(CALLBACK_INDENT+1) + 'out_msg.%s = in_msg.%s' % (map.getAttribute('to'), map.getAttribute('from') )
                )
            if type == MAP_TYPE.CODE:
                callback_statements.append(
                    indent(CALLBACK_INDENT+1) + map.getAttribute('code')
                )
        # publish message
        if DIRECTION == 'ros2lcm':
            callback_statements.append(
                indent(CALLBACK_INDENT+1) + ( CALLBACK_PUBLISH['ros2lcm'] % ('self.lcmpy', output_ch_name) )
            )
        if DIRECTION == 'lcm2ros':
            callback_statements.append(
                indent(CALLBACK_INDENT+1) + ( CALLBACK_PUBLISH['lcm2ros'] % ('self.'+publisher_name,) )
            )
        # compile callback
        callback = '\n'.join(callback_statements)
        PLACEHOLDERS['callbacks'].append(callback)
        # parse options
        # TODO
        # keep some stats
        enabled_links.append(
            '[%s](%s) ==> [%s](%s)' % (
                '%s/%s' % (input_ch.getAttribute('pkg'), input_ch.getAttribute('type')),
                input_ch_name,
                '%s/%s' % (output_ch.getAttribute('pkg'), output_ch.getAttribute('type')),
                output_ch_name
            )
        )

    # print some stats
    print '\n' + ''.join(['='] * 100)
    print 'Bridge statistics:'
    print '\tDirection: %s' % DIRECTION
    print '\tNumber of links: %d' % len(links)
    print '\t\tEnabled: %d' % len(enabled_links)
    print '\t\tDisabled: %d' % disabled_links
    print '\tLinks:'
    print '\t\t' + '\n\t\t'.join(enabled_links)
    print ''.join(['='] * 100) + '\n'

    # create msgs import statements
    for msg_tuple in IMPORT_MSGS:
        type_import = 'from %s%s import %s' % msg_tuple
        PLACEHOLDERS['msgs_import'].append(type_import)

    # compile placeholders
    PLACEHOLDERS['msgs_import'] = '\n'.join(PLACEHOLDERS['msgs_import'])
    PLACEHOLDERS['publishers'] = '\n'.join(PLACEHOLDERS['publishers'])
    PLACEHOLDERS['subscribers'] = '\n'.join(PLACEHOLDERS['subscribers'])
    PLACEHOLDERS['callbacks'] = str('\n'+indent(CALLBACK_INDENT)+'\n').join(PLACEHOLDERS['callbacks'])

    # compile script
    module_out = MODULE_TEMPLATE.format(**PLACEHOLDERS).strip()

    # write to file
    filename = 'autogenerated_%s_bridge_module' % DIRECTION
    out_file = os.path.join(TEMP_DIR, filename+'.py')
    print 'Writing to "%s"... ' % out_file,
    with open(out_file, "w") as stream_out:
        stream_out.write(module_out)
        stream_out.flush()
    print 'Done!'

    # wait for a few secs
    print 'Loading module...'
    time.sleep(2)

    # import module
    sys.path = [TEMP_DIR] + sys.path
    exec( 'from %s import ROS4LCM_BridgeModule' % filename )

    # create bridge module and start it
    bridge = ROS4LCM_BridgeModule(DIRECTION)
    bridge.start()
