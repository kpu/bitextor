#!/usr/bin/env python3

import numpy as np
import pylab as plt
import tensorflow as tf
import random
from collections import namedtuple
import mysql.connector

######################################################################################
def StrNone(arg):
    if arg is None:
        return "None"
    else:
        return str(arg)
######################################################################################
class LearningParams:
    def __init__(self):
        self.gamma = 1 #0.99
        self.lrn_rate = 0.1
        self.q_lrn_rate = 1
        self.max_epochs = 50001
        self.eps = 1  # 0.7
        self.maxBatchSize = 64
        self.debug = False
        self.walk = 1000
        self.NUM_ACTIONS = 15

######################################################################################
class Qnetwork():
    def __init__(self, params, env):
        # These lines establish the feed-forward part of the network used to choose actions
        EMBED_DIM = 90

        INPUT_DIM = EMBED_DIM // params.NUM_ACTIONS

        HIDDEN_DIM = 128

        # EMBEDDINGS
        self.embeddings = tf.Variable(tf.random_uniform([env.ns, INPUT_DIM], 0, 0.01))

        self.input = tf.placeholder(shape=[None, params.NUM_ACTIONS], dtype=tf.int32)

        self.embedding = tf.nn.embedding_lookup(self.embeddings, self.input)
        self.embedding = tf.reshape(self.embedding, [tf.shape(self.input)[0], EMBED_DIM])

        # HIDDEN 1
        self.hidden1 = self.embedding

        self.Whidden1 = tf.Variable(tf.random_uniform([EMBED_DIM, EMBED_DIM], 0, 0.01))
        self.hidden1 = tf.matmul(self.hidden1, self.Whidden1)

        #self.BiasHidden1 = tf.Variable(tf.random_uniform([1, EMBED_DIM], 0, 0.01))
        #self.hidden1 = tf.add(self.hidden1, self.BiasHidden1)

        self.hidden1 = tf.math.l2_normalize(self.hidden1, axis=1)
        #self.hidden1 = tf.nn.relu(self.hidden1)

        # HIDDEN 2
        self.hidden2 = self.hidden1

        self.Whidden2 = tf.Variable(tf.random_uniform([EMBED_DIM, HIDDEN_DIM], 0, 0.01))

        self.hidden2 = tf.matmul(self.hidden2, self.Whidden2)

        self.BiasHidden2 = tf.Variable(tf.random_uniform([1, HIDDEN_DIM], 0, 0.01))

        self.hidden2 = tf.add(self.hidden2, self.BiasHidden2)

        # OUTPUT
        self.Wout = tf.Variable(tf.random_uniform([HIDDEN_DIM, params.NUM_ACTIONS], 0, 0.01))

        self.Qout = tf.matmul(self.hidden2, self.Wout)

        self.predict = tf.argmax(self.Qout, 1)

        self.sumWeight = tf.reduce_sum(self.Wout) \
                        + tf.reduce_sum(self.BiasHidden2) \
                        + tf.reduce_sum(self.Whidden2) \
                        + tf.reduce_sum(self.Whidden1)

        # Below we obtain the loss by taking the sum of squares difference between the target and prediction Q values.
        self.nextQ = tf.placeholder(shape=[None, params.NUM_ACTIONS], dtype=tf.float32)
        self.loss = tf.reduce_sum(tf.square(self.nextQ - self.Qout))
        #self.trainer = tf.train.GradientDescentOptimizer(learning_rate=lrn_rate)
        self.trainer = tf.train.AdamOptimizer() #learning_rate=lrn_rate)
        
        self.updateModel = self.trainer.minimize(self.loss)

    def PrintQ(self, curr, params, env, sess):
        # print("hh", next, hh)
        visited = set()

        childNodeIds = env.GetChildNodes(curr, visited, params)
        a, allQ = sess.run([self.predict, self.Qout], feed_dict={self.input: childNodeIds})
        #print("curr=", curr, "a=", a, "allQ=", allQ, childNodeIds)
        print("curr=", curr, allQ, childNodeIds)

    def PrintAllQ(self, params, env, sess):
        print("         Q-values                          Next state")
        for curr in range(env.ns):
            self.PrintQ(curr, params, env, sess)

######################################################################################
# helpers
class MySQL:
    def __init__(self):
        # paracrawl
        self.mydb = mysql.connector.connect(
        host="localhost",
        user="paracrawl_user",
        passwd="paracrawl_password",
        database="paracrawl",
        charset='utf8'
        )
        self.mydb.autocommit = False
        self.mycursor = self.mydb.cursor(buffered=True)

######################################################################################
class Env:
    def __init__(self, sqlconn, url):
        self.ns = 31  # number of states
        self.numAligned = 0

        # all nodes with docs
        sql = "select url.id, url.document_id, document.lang, url.val from url, document where url.document_id = document.id and val like %s"
        val = (url + "%",)
        sqlconn.mycursor.execute(sql, val)
        res = sqlconn.mycursor.fetchall()
        assert (res is not None)

        self.nodes = {} # indexed by URL id
        self.nodesbyURL = {} # indexed by URL
        self.nodesById = []

        # stop node
        node = Node(sqlconn, 0, 0, 0, "", "STOP")
        self.nodes[node.urlId] = node
        self.nodesbyURL[node.url] = node
        self.nodesById.append(node)

        for rec in res:
            #print("rec", rec[0], rec[1])
            id = len(self.nodes)
            node = Node(sqlconn, id, rec[0], rec[1], rec[2], rec[3])
            self.nodes[node.urlId] = node
            self.nodesbyURL[node.url] = node
            self.nodesById.append(node)

            if node.aligned:
                self.numAligned += 1
        #print("nodes", len(self.nodes))
        print("numAligned", self.numAligned)

        self.nodesWithDoc = self.nodes.copy()
        print("nodesWithDoc", len(self.nodesWithDoc))

        # links between nodes, possibly to nodes without doc
        for node in self.nodesWithDoc.values():
            node.CreateLinks(sqlconn, self.nodes, self.nodesbyURL, self.nodesById)
            print(node.Debug())
        
        print("all nodes", len(self.nodes))

        # lang id
        self.langIds = {}

        # print out
        #for node in self.nodes.values():
        #    print("node", node.Debug())

        #node = Node(sqlconn, url, True)
        #print("node", node.docId, node.urlId)       


    def GetNextState(self, action, childNodeIds):
        nextNodeId = childNodeIds[0, action]
        nextNode = self.nodesById[nextNodeId]
        if nextNodeId == 0:
            rewardNode = 0
        elif nextNode.aligned:
            rewardNode = 8.5
        else:
            rewardNode = -1        

        return nextNodeId, rewardNode

    def GetChildNodes(self, curr, visited, params):
        currNode = self.nodesById[curr]
        #print("currNode", currNode.Debug())

        childNodeIds = []
        for link in currNode.links:
            childNode = link.childNode
            childNodeId = childNode.id
            #print("   ", childNode.Debug())
            if childNodeId != curr and childNodeId not in visited:
                childNodeIds.append(childNodeId)
        #print("   childNodeIds", childNodeIds)

        for i in range(len(childNodeIds), params.NUM_ACTIONS):
            childNodeIds.append(0)

        childNodeIds = np.array(childNodeIds)
        childNodeIds = childNodeIds.reshape([1, params.NUM_ACTIONS])

        return childNodeIds

    def Walk(self, start, params, sess, qn, printQ):
        visited = set()
        curr = start
        i = 0
        totReward = 0
        print(str(curr) + "->", end="")
        debugStr = ""

        while True:
            # print("curr", curr)
            # print("hh", next, hh)
            childNodeIds = self.GetChildNodes(curr, visited, params)
            action, allQ = sess.run([qn.predict, qn.Qout], feed_dict={qn.input: childNodeIds})
            action = action[0]
            next, reward = self.GetNextState(action, childNodeIds)
            totReward += reward
            visited.add(next)

            nextNode = self.nodesById[next]
            aligned = nextNode.aligned
            alignedStr = ""
            if aligned:
                alignedStr = "*"

            if printQ:
                debugStr += "   " + str(action) + " " + str(allQ) + " " + str(childNodeIds) + "\n"

            #print("(" + str(action) + ")", str(next) + "(" + str(reward) + ") -> ", end="")
            print(str(next) + alignedStr + "->", end="")
            curr = next

            if next == 0: break

            i += 1

        print(" ", totReward)

        if printQ:
            print(debugStr)


    def WalkAll(self, params, sess, qn):
        for start in range(self.ns):
            self.Walk(start, params, sess, qn, False)

    def GetNumberAligned(self, path):
        ret = 0
        for transition in path:
            next = transition.next
            nextNode = self.nodesById[next]
            if nextNode.aligned:
                ret += 1
        return ret

######################################################################################

class Node:
    def __init__(self, sqlconn, id, urlId, docId, lang, url):
        self.id = id
        self.urlId = urlId
        self.docId = docId
        self.lang = lang
        self.url = url
        self.links = []
        self.aligned = False

        if self.docId is not None:
            sql = "select * from document_align where document1 = %s or document2 = %s"
            val = (self.docId,self.docId)
            #print("sql", sql)
            sqlconn.mycursor.execute(sql, val)
            res = sqlconn.mycursor.fetchall()
            #print("aligned",  self.url, self.docId, res)

            if len(res) > 0:
                self.aligned = True

        #print(self.Debug())

    def Debug(self):
        strLinks = ""
        for link in self.links:
            #strLinks += str(link.parentNode.id) + "->" + str(link.childNode.id) + " "
            strLinks += str(link.childNode.id) + " "

        return " ".join([str(self.id), str(self.urlId), 
                        StrNone(self.docId), StrNone(self.lang), 
                        str(self.aligned), self.url,
                        "links=", str(len(self.links)), ":", strLinks ] )

    def CreateLinks(self, sqlconn, nodes, nodesbyURL, nodesById):
        #sql = "select id, text, url_id from link where document_id = %s"
        sql = "select link.id, link.text, link.text_lang, link.url_id, url.val from link, url where url.id = link.url_id and link.document_id = %s"
        val = (self.docId,)
        #print("sql", sql)
        sqlconn.mycursor.execute(sql, val)
        res = sqlconn.mycursor.fetchall()
        assert (res is not None)

        for rec in res:
            text = rec[1]
            textLang = rec[2]
            urlId = rec[3]
            url = rec[4]
            #print("urlid", self.docId, text, urlId)

            if urlId in nodes:
                childNode = nodes[urlId]
                #print("child", self.docId, childNode.Debug())
            else:
                continue
                #id = len(nodes)
                #childNode = Node(sqlconn, id, urlId, None, None, url)
                #nodes[childNode.urlId] = childNode
                #nodesbyURL[childNode.url] = childNode
                #nodesById.append(childNode)

            Link = namedtuple("Link", "text textLang parentNode childNode")
            link = Link(text, textLang, self, childNode)
            self.links.append(link)

######################################################################################

######################################################################################

def Neural(epoch, curr, params, env, sess, qn, visited):
    # NEURAL
    #print("curr", curr, visited)
    childNodeIds = env.GetChildNodes(curr, visited, params)
    action, allQ = sess.run([qn.predict, qn.Qout], feed_dict={qn.input: childNodeIds})
    action = action[0]
    if np.random.rand(1) < params.eps:
        action = np.random.randint(0, params.NUM_ACTIONS)

    next, r = env.GetNextState(action, childNodeIds)

    if curr == 0 and next == 0:
        done = True
    else:
        done = False

    visited.add(next)

    # Obtain the Q' values by feeding the new state through our network
    if curr == 0:
        targetQ = np.zeros([1, params.NUM_ACTIONS])
        maxQ1 = 0
    else:
        # print("  hh2", hh2)
        nextChildNodeIds = env.GetChildNodes(next, visited, params)
        Q1 = sess.run(qn.Qout, feed_dict={qn.input: nextChildNodeIds})
        # print("  Q1", Q1)
        maxQ1 = np.max(Q1)

        #targetQ = allQ
        targetQ = np.array(allQ, copy=True)
        #print("  targetQ", targetQ)
        newVal = r + params.gamma * maxQ1
        #targetQ[0, a] = (1 - params.q_lrn_rate) * targetQ[0, a] + params.q_lrn_rate * newVal
        targetQ[0, action] = newVal
        #print("  targetQ", targetQ)

    #print("  targetQ", targetQ, maxQ1)
    #print("  new Q", a, allQ)

    Transition = namedtuple("Transition", "curr next done childNodeIds targetQ")
    transition = Transition(curr, next, done, np.array(childNodeIds, copy=True), np.array(targetQ, copy=True))

    return transition

def UpdateQN(params, env, sess, qn, batch):
    batchSize = len(batch)
    #print("batchSize", batchSize)
    childNodeIds = np.empty([batchSize, params.NUM_ACTIONS], dtype=np.int)
    targetQ = np.empty([batchSize, params.NUM_ACTIONS])

    i = 0
    for transition in batch:
        curr = transition.curr
        next = transition.next

        childNodeIds[i, :] = transition.childNodeIds
        targetQ[i, :] = transition.targetQ
    
        i += 1

    _, loss, sumWeight = sess.run([qn.updateModel, qn.loss, qn.sumWeight], feed_dict={qn.input: childNodeIds, qn.nextQ: targetQ})

    #print("loss", loss)
    return loss, sumWeight

def Trajectory(epoch, curr, params, env, sess, qn):
    path = []
    visited = set()

    while (True):
        transition = Neural(epoch, curr, params, env, sess, qn, visited)
        path.append(transition)
        curr = transition.next
        #print("visited", visited)

        if transition.done: break
    #print("path", path)

    return path

######################################################################################
class Corpus:
    def __init__(self, params):
        self.transitions = []

    def AddPath(self, path):
        for transition in path:
            self.transitions.append(transition)


    def GetBatch(self, maxBatchSize):        
        batch = self.transitions[0:maxBatchSize]
        self.transitions = self.transitions[maxBatchSize:]

        return batch

######################################################################################

def Train(params, env, sess, qn):
    losses = []
    sumWeights = []
    corpus = Corpus(params)

    for epoch in range(params.max_epochs):
        #startState = np.random.randint(0, env.ns)  # random start state
        startState = 30
        path = Trajectory(epoch, startState, params, env, sess, qn)
        corpus.AddPath(path)

        while len(corpus.transitions) >= params.maxBatchSize:
            #print("corpusSize", corpusSize)
            
            batch = corpus.GetBatch(params.maxBatchSize)
  
            loss, sumWeight = UpdateQN(params, env, sess, qn, batch)
            losses.append(loss)
            sumWeights.append(sumWeight)

        if epoch > 0 and epoch % params.walk == 0:
            qn.PrintAllQ(params, env, sess)
            env.WalkAll(params, sess, qn)
            #env.Walk(9, sess, qn, True)
            print("epoch", epoch, "loss", losses[-1])
            print()

        # add to batch
        endState = path[-1].next

        numAligned = env.GetNumberAligned(path)
        #print("path", numAligned, path)
        if numAligned >= env.numAligned - 1:
            print("got them all!")
            #eps = 1. / ((i/50) + 10)
            params.eps *= .999
            params.eps = max(0.1, params.eps)
            #print("eps", params.eps)
            
            #params.q_lrn_rate * 0.999
            #params.q_lrn_rate = max(0.1, params.q_lrn_rate)
            #print("q_lrn_rate", params.q_lrn_rate)
            

    # LAST BATCH
            
    return losses, sumWeights

######################################################################################

def Main():
    print("Starting")
    np.random.seed()
    np.set_printoptions(formatter={'float': lambda x: "{0:0.2f}".format(x)})

    # =============================================================
    sqlconn = MySQL()
    #siteMap = Sitemap(sqlconn, "www.visitbritain.com")
    # =============================================================
    env = Env(sqlconn, "www.vade-retro.fr/")

    params = LearningParams()

    tf.reset_default_graph()
    qn = Qnetwork(params, env)
    init = tf.global_variables_initializer()
    print("qn.Qout", qn.Qout)

    with tf.Session() as sess:
        sess.run(init)

        qn.PrintAllQ(params, env, sess)
        #env.WalkAll(params, sess, qn)
        print()

        losses, sumWeights = Train(params, env, sess, qn)
        print("Trained")
        print(env)
        
        #qn.PrintAllQ(params, env, sess)
        #env.WalkAll(params, sess, qn)

        env.Walk(30, params, sess, qn, True)

        plt.plot(losses)
        plt.show()

        plt.plot(sumWeights)
        plt.show()

    print("Finished")


if __name__ == "__main__":
    Main()
