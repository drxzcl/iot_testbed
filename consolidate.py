import time
import datetime
import logging
from google.appengine.ext import ndb
import json

from models import Measurement, MeasurementBlock

BLOCK_SIZE = 15


# BLOCK_DEPTH = 3 # Currently unused.

def consolidate_blocks(identifier, type_, depth):
    blocks = MeasurementBlock.query(MeasurementBlock.identifier == identifier, MeasurementBlock.type == type_,
                                    MeasurementBlock.count == BLOCK_SIZE ** depth).order(MeasurementBlock.first).fetch(
        keys_only=True)
    logging.info('There are %d blocks at size %d.' % (len(blocks), BLOCK_SIZE ** depth))
    i = 0
    if len(blocks) >= BLOCK_SIZE:
        blocks = ndb.get_multi(blocks)
        for blocknr in range(len(blocks) // BLOCK_SIZE):
            blockdata = []
            first, last = datetime.datetime(2999, 12, 31), datetime.datetime(1000, 1, 1)
            for bnr in range(BLOCK_SIZE):
                block = blocks[i]
                i += 1
                first = min(first, block.first)
                last = max(last, block.last)
                blockdata.extend(json.loads(block.values))
                block.key.delete()

            metablock = MeasurementBlock(identifier=identifier, type=type_, count=BLOCK_SIZE ** (depth + 1),
                                         first=first, last=last, values=json.dumps(blockdata))
            metablock.put()

    return "Ok."


def consolidate_measurements(identifier, type_):
    # aggregate the individual measurements
    measurements = Measurement.all(identifier, type_).order(Measurement.timestamp).fetch(keys_only=True)
    logging.info('There are %d measurements' % (len(measurements),))
    i = 0
    if len(measurements) >= BLOCK_SIZE:
        measurements = ndb.get_multi(measurements)
        for blocknr in range(len(measurements) // BLOCK_SIZE):
            blockdata = []
            to_delete = []
            first, last = datetime.datetime(2999, 12, 31), datetime.datetime(1000, 1, 1)
            for mnr in range(BLOCK_SIZE):
                measurement = measurements[i]
                if not measurement:
                    return "Odd stuff."
                i += 1
                ts = measurement.timestamp
                blockdata.append((int(time.mktime(ts.timetuple())), measurement.value))
                first = min(first, ts)
                last = max(last, ts)
                to_delete.append(measurement.key)

            # Full block, add it
            block = MeasurementBlock(identifier=identifier, type=type_,
                                     count=BLOCK_SIZE, first=first, last=last,
                                     values=json.dumps(blockdata))
            block.put()
            ndb.delete_multi(to_delete)

    consolidate_blocks(identifier, type_, 1)
    consolidate_blocks(identifier, type_, 2)

    return "Ok."
