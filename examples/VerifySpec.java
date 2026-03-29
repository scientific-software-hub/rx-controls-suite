///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.reactivestreams:reactive-streams-tck:1.0.4
//DEPS org.testng:testng:6.14.3
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../src/RxTango.java ../src/RxTangoAttribute.java ../src/RxTangoCommand.java
//SOURCES ../src/RxTangoAttributeWrite.java ../src/RxTangoAttributeChangePublisher.java
//SOURCES ../src/RxTangoPublisherVerification.java

import org.testng.TestNG;
import org.testng.xml.XmlClass;
import org.testng.xml.XmlSuite;
import org.testng.xml.XmlTest;

import java.util.ArrayList;
import java.util.List;

/**
 * Runs the reactive-streams TCK against RxTangoAttribute.
 *
 * Requires the Tango stack to be running (docker compose up -d).
 *
 * Usage:
 *   jbang examples/VerifySpec.java
 *
 * Override device/attribute:
 *   jbang -Dtango.device=tango://host:10000/my/dev/1 \
 *         -Dtango.attribute=my_attr \
 *         examples/VerifySpec.java
 */
public class VerifySpec {
    public static void main(String[] args) {
        XmlSuite suite = new XmlSuite();
        suite.setName("ReactiveStreamsTCK");

        XmlTest test = new XmlTest(suite);
        test.setName("RxTangoAttribute");
        test.setXmlClasses(new ArrayList<>(List.of(
                new XmlClass("org.tango.client.rx.RxTangoPublisherVerification"))));
        suite.setTests(new ArrayList<>(List.of(test)));

        TestNG testng = new TestNG();
        testng.setVerbose(2);
        testng.setXmlSuites(new ArrayList<>(List.of(suite)));
        testng.run();

        System.exit(testng.hasFailure() ? 1 : 0);
    }
}
