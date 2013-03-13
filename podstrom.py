#!/usr/bin/env python

import subprocess as SP

magic_marker = 'podstrom-original-id: '


class Runner(object):

    def __init__(self, subpath, logstream=None):
        self.logstream = logstream
        self.subpath = subpath
        self.cache = self.make_cache()
        self.checker = self.run_batch_checker()
        self.empty_tree = SP.check_output(
            ['git', 'hash-object', '-w', '-t', 'tree', '/dev/null']).strip()

    def log(self, message):
        if self.logstream:
            print >>self.logstream, message

    def make_cache(self):
        self.log("getting log...")
        log = SP.check_output(['git', 'log', '--all', '--format=raw'])
        self.log("parsing log...")
        current = None
        cache = {}
        for line in log.split('\n'):
            if line.startswith('commit '):
                current = line[7:]
            if line.startswith('    '+magic_marker) and current:
                original = line[len('    '+magic_marker):]
                cache[original] = current
        self.log("found {} subtree commits".format(len(cache)))
        return cache

    def run_batch_checker(self):
        return SP.Popen(['git', 'cat-file', '--batch-check'],
                        stdin=SP.PIPE, stdout=SP.PIPE)

    def close(self):
        self.checker.stdin.close()

    def transform_tree(self, orighash):
        self.checker.stdin.write(orighash + ':' + self.subpath + '\n')
        result = self.checker.stdout.readline()
        if result.endswith('missing\n'): return self.empty_tree
        hash, type, size = result.split()
        if type != 'tree': return self.empty_tree
        return hash

    def transform_commit(self, orighash):
        if orighash in self.cache: return self.cache[orighash]
        body = SP.check_output(['git', 'cat-file', 'commit', orighash])
        header, message = body.split('\n\n', 1)

        self.log("loading " + message.partition('\n')[0])
        newheader = []
        for line in header.split('\n'):
            if line.startswith('tree '):
                newtree = self.transform_tree(line[5:])
                if not newtree: return None
                newheader.append('tree ' + newtree)
            elif line.startswith('parent '):
                newparent = self.transform_commit(line[7:])
                if newparent: newheader.append('parent ' + newparent)
            else:
                newheader.append(line)

        newcontent = ('\n'.join(newheader) + '\n\n' + message +
                      '\n' + magic_marker + orighash + '\n')

        self.log("saving " + message.partition('\n')[0])
        hash_object = SP.Popen(
            ['git', 'hash-object', '-t', 'commit', '-w', '--stdin'],
            stdin=SP.PIPE, stdout=SP.PIPE)
        output, _ = hash_object.communicate(newcontent)
        if hash_object.returncode != 0:
            raise OSError("hash-object returned %d" % hash_object.returncode)

        newhash = output.strip()
        self.cache[orighash] = newhash
        return newhash


if __name__ == '__main__':
    import sys
    import argparse
    parser = argparse.ArgumentParser(description='Create a Git subtree.')
    parser.add_argument('revs', metavar='rev', nargs='+',
                        help='the commits to get a subtree for')
    parser.add_argument('-p', '--path', required=True,
                        help='the directory path to extract')
    parser.add_argument('-u', '--update', metavar='ref',
                        help='put the result in this branch')
    args = parser.parse_args()
    if args.update and len(args.revs) > 1:
        parser.error('only one input commit may be given when updating')
    runner = Runner(args.path, logstream=sys.stderr)
    results = []
    for rev in args.revs:
        rev = SP.check_output(['git', 'rev-parse', rev]).strip()
        results.append(runner.transform_commit(rev))
    if args.update:
        SP.check_call(['git', 'update-ref', '-m', 'running podstrom',
                       'refs/heads/' + args.update, results[0]])
    else:
        for rev in results:
            print rev
    runner.close()
