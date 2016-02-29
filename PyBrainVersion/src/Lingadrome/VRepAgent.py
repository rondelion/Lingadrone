# -*- coding: utf-8 -*-
'''
Created on 2015/09/08
PyBrain version 2016-02-11
@author: rondelion
'''
# import sys
import math
from pybrain.rl.learners.valuebased import ActionValueTable
from pybrain.rl.learners import Q

from AgentMind import AgentMind
from Locomotion.LocomotionTask import LocomotionTask
from Locomotion.LocomotionEnvironment import LocomotionEnvironment

from VRepObject import VRepObject
try:
    import vrep
except:
    print ('VRepBubbleRob--------------------------------------------------------------')
    print ('"vrep.py" could not be imported. This means very probably that')
    print ('either "vrep.py" or the remoteApi library could not be found.')
    print ('Make sure both are in the same folder as this file,')
    print ('or appropriately adjust the file "vrep.py"')
    print ('--------------------------------------------------------------')
    print ('')
    exit(-1)

class VRepAgent(VRepObject):
    '''
    classdocs
    '''
    __DistanceSalienceAttenuationCoefficient=-1.0
    ItemContactLimit=0.02
    ItemNearLimit=1.0
    ItemDirectionAhead=0.1
    BlockJudgeCount=500
    RelativeTranslation=0.0001
    DirectionAhead=0.01

    def __init__(self, name, clientID, sensorHandle, bodyHandle):
        '''
        Constructor
        '''
        self.__velocity=0.0        # m/s
        self.__linearVelocity=None # vector
        self.__angularVelocity=0.0 # radian/s
        self.__orientation=None    # π radian
        self.__steering=0.0        # Steering value [-1,1]
        self.__thrust=1.0          # Accelerator value [-1,1]
        self.__emotion=0
        self.__position=None
        self.__initLoop=True
        self.__perceivedItems={}
        controller = ActionValueTable(150, 5)   # pyBrain
        controller.initialize(1.)               # pyBrain
        learner = Q()                           # pyBrain
        self.__mind=AgentMind(controller, learner)  # with pyBrain
        self.__name=name
        self.__clientID=clientID          # Client ID of the Dummy object
        self.__sensorHandle=sensorHandle  # Proximity sensor handle of the V-Rep agent
        self.__bodyHandle=bodyHandle      # BubbleRob body handle
        self.__driveBackStartTime=-99000
        self.__firstOrientation=None
        self.__cnt=0
        self.__mind.setInput("name", name)
        self.__pybrainEnvironment = LocomotionEnvironment()
        self.__pybrainTask = LocomotionTask(self.__pybrainEnvironment)
        self.__carryingDirection = 0
        self.__thrustIntegral=0.0
        self.__thrustHistory = [0]*self.BlockJudgeCount
        self.__positionHistory = [[0.0,0.0]]*self.BlockJudgeCount   # May cause a bug
        self.__blocked=False
   
    def getName(self):
        return self.__name

    def getType(self):
        return "Agent"

    def loop(self):
        operationMode=vrep.simx_opmode_streaming
        if self.__initLoop:
            self.__initLoop=False
        else:
            operationMode=vrep.simx_opmode_buffer
        returnCode, orientation = vrep.simxGetObjectOrientation(self.__clientID, self.__bodyHandle, -1, operationMode)
        if returnCode==vrep.simx_return_ok:
            self.__orientation=orientation[2]
        else:
            self.__orientation = None
            # print >> sys.stderr, "Error in VRepBubbleRob.getOrientation()"
        self.__mind.setInput("orientation", self.__orientation)
        returnCode, position = vrep.simxGetObjectPosition(self.__clientID, self.__bodyHandle, -1, operationMode)
        if returnCode==vrep.simx_return_ok:
            self.__position=[0.0,0.0]
            self.__position[0]=position[0]  #X
            self.__position[1]=position[1]  #Y
        else:
            self.__position=None
            # print >> sys.stderr, "Error in VRepBubbleRob.getPosition()"
        returnCode, linearVelocity, angularVelocity = vrep.simxGetObjectVelocity(self.__clientID, self.__bodyHandle, operationMode)
        if returnCode==vrep.simx_return_ok:
            try:
                # self.__velocity=linearVelocity[0]*math.cos(self.__orientation)+linearVelocity[1]*math.sin(self.__orientation)
                self.__velocity=math.sqrt(linearVelocity[0]**2+linearVelocity[1]**2)
                self.__mind.setInput("velocity", self.__velocity)
                self.__linearVelocity=linearVelocity
            except TypeError:
                pass
                # if self.__name=="BubbleRob#1":
                #    print self.__velocity, linearVelocity[0], math.cos(self.__orientation), linearVelocity[1], math.sin(self.__orientation)
        else:
            self.__velocity=None
            # print >> sys.stderr, "Error in VRepBubbleRob.getPosition()"
        returnCode, sensorTrigger, dp, doh, dsnv = vrep.simxReadProximitySensor(self.__clientID, self.__sensorHandle, operationMode)
        if returnCode==vrep.simx_return_ok:
            # We succeeded at reading the proximity sensor
            self.__mind.setInput("lastProximitySensorTime", vrep.simxGetLastCmdTime(self.__clientID))
            self.__mind.setInput("sensorTrigger", sensorTrigger)
        self.blocked()  # judge if blocked
        self.__pybrainObservation()
        self.__mind.applyRules()
        self.__mind.setStates()
        self.output()
        # increment counter
        self.__cnt=self.__cnt+1
            
    def output(self):
        if self.__mind.getOutput("steering")!=None:
            self.setSteering(self.__mind.getOutput("steering"))
        if self.__mind.getOutput("thrust")!=None:
            self.setThrust(self.__mind.getOutput("thrust"))
        if self.__mind.getOutput("reward")!=None:
            if self.__mind.getOutput("reward")>0.5:
                self.setEmotionalExpression(1)
            elif self.__mind.getOutput("reward")<-0.5:
                self.setEmotionalExpression(-1)
            else:
                self.setEmotionalExpression(0)
        getSignalReturnCode, dMessage = vrep.simxGetStringSignal(self.__clientID, "Debug", vrep.simx_opmode_streaming)
        if dMessage!="":
            print("Debug:"+dMessage)
        
    def setSteering(self, steering):
        # Steering value [-1,1]
        self.__steering = steering
        #if self.getName()=="BubbleRob#1":
        #    print self.getName(), steering
        vrep.simxSetFloatSignal(self.__clientID, self.__name+":Steering", self.__steering, vrep.simx_opmode_oneshot)
        # print self.__clientID, self.__name+":Steering", self.__steering
        
    def setThrust(self, thrust):
        # Average wheel speed
        self.__thrust = thrust
        vrep.simxSetFloatSignal(self.__clientID, self.__name+":Acceleration", self.__thrust, vrep.simx_opmode_oneshot)

    def getPosition(self):
        return self.__position

    def getOrientation(self):
        return self.__orientation
    
    def getVelocity(self):
        return self.__velocity

    def getAngularVelocity(self):
        return self.__angularVelocity
        # simxGetObjectVelocity

    def setEmotionalExpression(self, emotion):
        self.__emotion=emotion
        vrep.simxSetIntegerSignal(self.__clientID, self.__name+":Emotion", self.__emotion, vrep.simx_opmode_oneshot)
    
    def detectNearestItem(self):
        pass
        # return the id, direction, distance & features of the nearest item
    
    def setAttentionDirection(self, orientation):
        pass
    
    def setAttentionWidth(self, width):
        pass
    
    def setPerceivedItems(self, items):
        # set a list of perceived items
        self.__perceivedItems=items
        self.__visualSalience()
        self.__mind.setInput("perceivedItems", self.__perceivedItems)

    def __visualSalience(self):
        # give the score to perceived items
        for item in self.__perceivedItems:
            score=0.0
            if item.has_key("direction") and item.has_key("distance"):
                direction=item["direction"]
                if -0.5*math.pi<direction and direction<0.5*math.pi:
                    # FOV: [-90,90] degrees
                    score=math.cos(direction)*math.exp(VRepAgent.__DistanceSalienceAttenuationCoefficient*item["distance"])
            item["score"]=score

    def __setCarryingReward(self):
        reward = 0
        # calculate reward of carrying the most salient item for the task
        mostSalient = self.__mind.getMostSalient()
        if mostSalient!=None:
            velocityDirection = math.atan2(self.__linearVelocity[1], self.__linearVelocity[0])
            # TODO: normalization
            reward = math.cos(velocityDirection - self.__carryingDirection)
            # print "velocityDirection=",velocityDirection,"carryingD=", self.__carryingDirection, "RW=", reward
            # reward = self.__pybrainTask.getReward()
        return reward
        
    def setRewards(self):
        reward = 0.5 # self.__setCarryingReward()
        # print "carryingReward, blocked", reward, self.getBlockedStatus()
        reward = reward - self.getBlockedStatus()
        # print "reward=", reward
        self.__mind.giveReward(reward)
    
    def pybrainLearn(self):
        self.__mind.learn() # episodes=1 by default
    
    def pybrainReset(self):
        self.__mind.reset()
    
    def setCarryingDirection(self, direction):
        print "setCarryingDirection:", direction 
        self.__carryingDirection = direction
    
    def __pybrainObservation(self):
        mostSalient=self.__mind.getMostSalient()
        self.__pybrainTask.setItemDistance(self.getMostSalientItemDistance(mostSalient))
        self.__pybrainTask.setItemDirection(self.getMostSalientItemDirection(mostSalient))
        self.__pybrainTask.setRelativeCarryingDirection(self.getRelativeCarryingDirection())
        self.__pybrainTask.setBlockedStatus(self.getBlockedStatus())
        self.__mind.integrateObservation(self.__pybrainTask.getObservation())

    def getMostSalientItemDistance(self, item):
        distance=2
        if item!=None and item.has_key("distance"):
            d = item["distance"]
            if d<self.ItemContactLimit:
                distance=0
            elif d<self.ItemNearLimit:
                distance=1
        return distance
    
    def getMostSalientItemDirection(self, item):
        direction=0
        if item!=None and item.has_key("direction"):
            d = item["direction"]
            if math.fabs(d)>self.DirectionAhead:
                if d>0:
                    if d<0.5*math.pi:
                        direction=2 # Left forward
                    else:
                        direction=4 # Left backward
                else:
                    if d>-0.5*math.pi:
                        direction=1 # Right forward
                    else:
                        direction=3 # Right backward
        return direction
    
    def getRelativeCarryingDirection(self):
        direction=0
        if self.__orientation!=None and self.__carryingDirection!=None:
            d = self.__carryingDirection - self.__orientation
            if math.fabs(d)>self.DirectionAhead:
                if d>0:
                    if d<0.5*math.pi:
                        direction=2 # Left forward
                    else:
                        direction=4 # Left backward
                else:
                    if d>-0.5*math.pi:
                        direction=1 # Right forward
                    else:
                        direction=3 # Right backward
        return direction
    
    def getBlockedStatus(self):
        status = 0
        if self.__blocked:
            status = 1
        return status
    
    def blocked(self):
        # Judge blocked iff translation for a period is fractional relative to thrust integration
        self.__blocked = False
        pointer=self.__cnt % self.BlockJudgeCount
        pLast=(self.__cnt+1) % self.BlockJudgeCount
        self.__thrustHistory[pointer]=self.__thrust
        self.__thrustIntegral=self.__thrustIntegral+self.__thrust-self.__thrustHistory[pLast]
        self.__positionHistory[pointer]=self.__position
        if self.__cnt>=self.BlockJudgeCount and self.__thrustIntegral!=0.0 and self.__positionHistory[pLast]!=None:
            d = math.sqrt((self.__position[0]-self.__positionHistory[pLast][0])**2 + \
                          (self.__position[1]-self.__positionHistory[pLast][1])**2)
            if d/self.__thrustIntegral < self.RelativeTranslation:
                self.__blocked = True
                # print "blocked!", d, self.__thrustIntegral, d/self.__thrustIntegral